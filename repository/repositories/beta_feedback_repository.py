from __future__ import annotations

import json
import re

from sqlalchemy import func

from repository.database import SessionLocal, initialize_database
from repository.models.beta_feedback_model import BetaFeedbackModel
from repository.models.beta_issue_model import BetaIssueModel
from repository.models.beta_user_model import BetaUserModel
from repository.models.prediction_record_model import PredictionRecordModel
from utils.time import utc_now

INITIAL_PICKS = {"Over", "Under", "Unsure"}
FINAL_PICKS = {"Over", "Under", "Pass"}
WOULD_PICK = {"Yes", "No", "Unsure"}
WOULD_PAY = {"", "Free", "$9.99/month", "$19.99/month", "$29.99/month", "$49.99/month", "I would not subscribe"}
BUG_CATEGORIES = {
    "Wrong player data",
    "Wrong line",
    "Prediction seems incorrect",
    "Settlement/result issue",
    "Page/interface problem",
    "Performance issue",
    "Other",
}


class BetaFeedbackRepository:
    @staticmethod
    def submit(user_id: int, session_id: str, payload: dict) -> dict:
        initialize_database()
        initial = _choice(payload.get("initial_pick"), INITIAL_PICKS, "initial opinion")
        final = _choice(payload.get("final_pick"), FINAL_PICKS, "final decision")
        would_pick = _choice(payload.get("would_pick"), WOULD_PICK, "pick intent")
        would_pay = str(payload.get("would_pay") or "").strip()
        if would_pay not in WOULD_PAY:
            raise ValueError("Choose one of the available pricing options.")
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        prediction_id = _optional_id(payload.get("prediction_record_id"))
        entry_prop_id = _optional_id(payload.get("entry_prop_id"))
        now = utc_now().replace(tzinfo=None)
        with SessionLocal() as session:
            query = session.query(BetaFeedbackModel).filter(BetaFeedbackModel.user_id == int(user_id))
            if prediction_id is not None:
                query = query.filter(BetaFeedbackModel.prediction_record_id == prediction_id)
            elif entry_prop_id is not None:
                query = query.filter(BetaFeedbackModel.entry_prop_id == entry_prop_id)
            else:
                query = query.filter(
                    BetaFeedbackModel.prediction_record_id.is_(None),
                    BetaFeedbackModel.entry_prop_id.is_(None),
                ).order_by(BetaFeedbackModel.created_at.desc())
            row = query.first()
            if row is None or (prediction_id is None and entry_prop_id is None and row.context_json != json.dumps(context, sort_keys=True)):
                row = BetaFeedbackModel(user_id=int(user_id), session_id=session_id, created_at=now)
                session.add(row)
            row.session_id = session_id
            row.prediction_record_id = prediction_id
            row.entry_id = _optional_id(payload.get("entry_id"))
            row.entry_prop_id = entry_prop_id
            row.useful = payload.get("useful") if isinstance(payload.get("useful"), bool) else None
            row.initial_pick = initial
            row.final_pick = final
            row.changed_decision = _decision_changed(initial, final)
            row.would_pick = would_pick
            row.would_pay = would_pay
            row.feedback_text = str(payload.get("feedback_text") or "").strip()[:2000]
            row.context_json = json.dumps(context, default=str, sort_keys=True)
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return _feedback_payload(row)

    @staticmethod
    def recent(limit: int = 30, *, user_id: int | None = None) -> list[dict]:
        initialize_database()
        with SessionLocal() as session:
            query = session.query(BetaFeedbackModel, BetaUserModel).join(
                BetaUserModel, BetaUserModel.id == BetaFeedbackModel.user_id
            )
            if user_id is not None:
                query = query.filter(BetaFeedbackModel.user_id == int(user_id))
            rows = query.order_by(BetaFeedbackModel.created_at.desc()).limit(max(1, min(limit, 100))).all()
            return [{**_feedback_payload(row), "tester": user.username} for row, user in rows]

    @staticmethod
    def for_prediction(prediction_record_id: int, limit: int = 100) -> list[dict]:
        initialize_database()
        with SessionLocal() as session:
            rows = session.query(BetaFeedbackModel, BetaUserModel).join(
                BetaUserModel, BetaUserModel.id == BetaFeedbackModel.user_id
            ).filter(
                BetaFeedbackModel.prediction_record_id == int(prediction_record_id)
            ).order_by(BetaFeedbackModel.created_at.desc()).limit(max(1, min(limit, 100))).all()
            return [{**_feedback_payload(row), "tester": user.username} for row, user in rows]

    @staticmethod
    def aggregate() -> dict:
        initialize_database()
        with SessionLocal() as session:
            rows = session.query(BetaFeedbackModel).all()
        total = len(rows)
        useful_answered = [row for row in rows if row.useful is not None]
        useful_yes = sum(1 for row in useful_answered if row.useful)
        changed = sum(1 for row in rows if row.changed_decision)
        changed_rate = _rate(changed, total)
        return {
            "total_feedback": total,
            "useful_yes": useful_yes,
            "useful_rate": _rate(useful_yes, len(useful_answered)),
            "changed_decision_count": changed,
            "changed_decision_rate": changed_rate,
            "decision_change_rate": changed_rate,
            "initial_over_count": sum(row.initial_pick == "Over" for row in rows),
            "initial_under_count": sum(row.initial_pick == "Under" for row in rows),
            "initial_unsure_count": sum(row.initial_pick == "Unsure" for row in rows),
            "final_over_count": sum(row.final_pick == "Over" for row in rows),
            "final_under_count": sum(row.final_pick == "Under" for row in rows),
            "final_pass_count": sum(row.final_pick == "Pass" for row in rows),
            "would_pay_distribution": {
                option: sum(row.would_pay == option for row in rows)
                for option in sorted(WOULD_PAY - {""})
            },
        }

    @staticmethod
    def segments() -> dict:
        initialize_database()
        with SessionLocal() as session:
            rows = session.query(BetaFeedbackModel, PredictionRecordModel).join(
                PredictionRecordModel,
                PredictionRecordModel.id == BetaFeedbackModel.prediction_record_id,
            ).filter(PredictionRecordModel.legacy_quarantined.is_(False)).all()
        buckets: dict[str, list] = {}
        sports: dict[str, list] = {}
        stats: dict[str, list] = {}
        platforms: dict[str, list] = {}
        for feedback, prediction in rows:
            buckets.setdefault(_confidence_bucket(prediction.probability), []).append((feedback, prediction))
            sports.setdefault(prediction.sport or "Unknown", []).append((feedback, prediction))
            stats.setdefault(prediction.stat or "Unknown", []).append((feedback, prediction))
            platforms.setdefault(prediction.platform or "Unknown", []).append((feedback, prediction))
        return {
            "confidence": _segment_payload(buckets),
            "sport": _segment_payload(sports),
            "stat": _segment_payload(stats),
            "platform": _segment_payload(platforms),
        }


class BetaIssueRepository:
    @staticmethod
    def submit(user_id: int, session_id: str, payload: dict) -> dict:
        initialize_database()
        issue_type = str(payload.get("issue_type") or "BUG").strip().upper()
        if issue_type not in {"BUG", "FEATURE"}:
            raise ValueError("Issue type must be BUG or FEATURE.")
        description = str(payload.get("description") or "").strip()
        if not 4 <= len(description) <= 4000:
            raise ValueError("Description must be between 4 and 4000 characters.")
        category = str(payload.get("category") or ("Other" if issue_type == "BUG" else "Feature request")).strip()[:80]
        if issue_type == "BUG" and category not in BUG_CATEGORIES:
            raise ValueError("Choose one of the available problem categories.")
        row = BetaIssueModel(
            user_id=int(user_id),
            session_id=session_id,
            prediction_record_id=_optional_id(payload.get("prediction_record_id")),
            entry_id=_optional_id(payload.get("entry_id")),
            entry_prop_id=_optional_id(payload.get("entry_prop_id")),
            issue_type=issue_type,
            category=category,
            description=description,
            normalized_key=_normalized_request(description),
            status="OPEN",
        )
        with SessionLocal() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return _issue_payload(row)

    @staticmethod
    def recent(limit: int = 50, issue_type: str | None = None) -> list[dict]:
        initialize_database()
        with SessionLocal() as session:
            query = session.query(BetaIssueModel, BetaUserModel).join(BetaUserModel)
            if issue_type:
                query = query.filter(BetaIssueModel.issue_type == issue_type.upper())
            rows = query.order_by(BetaIssueModel.created_at.desc()).limit(max(1, min(limit, 100))).all()
            return [{**_issue_payload(row), "tester": user.username} for row, user in rows]

    @staticmethod
    def counts() -> dict:
        initialize_database()
        with SessionLocal() as session:
            return {
                name: int(count)
                for name, count in session.query(BetaIssueModel.issue_type, func.count(BetaIssueModel.id))
                .group_by(BetaIssueModel.issue_type).all()
            }


def _choice(value: object, allowed: set[str], label: str) -> str:
    normalized = str(value or "").strip().title()
    match = next((item for item in allowed if item.lower() == normalized.lower()), None)
    if match is None:
        raise ValueError(f"Choose a valid {label}.")
    return match


def _optional_id(value: object) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _decision_changed(initial: str, final: str) -> bool:
    if initial == "Unsure":
        return final in {"Over", "Under"}
    if final == "Pass":
        return True
    return initial != final


def _normalized_request(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.lower())
    ignored = {"a", "an", "and", "for", "i", "in", "of", "the", "to", "with"}
    return " ".join(word for word in words if word not in ignored)[:160]


def _feedback_payload(row: BetaFeedbackModel) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "prediction_record_id": row.prediction_record_id,
        "entry_id": row.entry_id,
        "entry_prop_id": row.entry_prop_id,
        "useful": row.useful,
        "changed_decision": bool(row.changed_decision),
        "initial_pick": row.initial_pick,
        "final_pick": row.final_pick,
        "would_pick": row.would_pick,
        "would_pay": row.would_pay,
        "feedback_text": row.feedback_text,
        "context": _json(row.context_json),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _issue_payload(row: BetaIssueModel) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "prediction_record_id": row.prediction_record_id,
        "entry_id": row.entry_id,
        "entry_prop_id": row.entry_prop_id,
        "issue_type": row.issue_type,
        "category": row.category,
        "description": row.description,
        "normalized_key": row.normalized_key,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _json(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _rate(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100.0, 1) if denominator else 0.0


def _confidence_bucket(value: float) -> str:
    probability = float(value or 0)
    return "<55%" if probability < 55 else "55-60%" if probability < 60 else "60-65%" if probability < 65 else "65-70%" if probability < 70 else "70%+"


def _segment_payload(groups: dict[str, list]) -> list[dict]:
    result = []
    for label, rows in sorted(groups.items()):
        settled = [(feedback, prediction) for feedback, prediction in rows if prediction.outcome in {"Win", "Loss", "Push"}]
        wins = sum(prediction.outcome == "Win" for _, prediction in settled)
        losses = sum(prediction.outcome == "Loss" for _, prediction in settled)
        useful = [feedback for feedback, _ in rows if feedback.useful is not None]
        result.append({
            "label": label,
            "predictions": len(rows),
            "settled": len(settled),
            "wins": wins,
            "losses": losses,
            "hit_rate": _rate(wins, wins + losses),
            "useful_rate": _rate(sum(bool(row.useful) for row in useful), len(useful)),
            "decision_change_rate": _rate(sum(bool(row.changed_decision) for row, _ in rows), len(rows)),
            "sample_label": "Thin sample" if len(rows) < 20 else "Developing" if len(rows) < 100 else "Established",
        })
    return result
