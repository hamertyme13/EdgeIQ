from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func

from repository.database import SessionLocal, initialize_database
from repository.models.beta_feedback_model import BetaFeedbackModel
from repository.models.beta_session_model import BetaSessionModel
from repository.models.beta_user_model import BetaUserModel
from repository.models.product_event_model import ProductEventModel
from repository.repositories.beta_feedback_repository import BetaFeedbackRepository, BetaIssueRepository
from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository
from repository.repositories.product_experience_repository import ProductExperienceRepository
from utils.time import utc_now


def beta_summary() -> dict:
    initialize_database()
    now = utc_now().replace(tzinfo=None)
    week_ago = now - timedelta(days=7)
    with SessionLocal() as session:
        users = session.query(BetaUserModel).filter(BetaUserModel.is_beta_tester.is_(True)).all()
        sessions = session.query(func.count(BetaSessionModel.id)).scalar() or 0
        event_counts = {
            name: int(count)
            for name, count in session.query(ProductEventModel.event_name, func.count(ProductEventModel.id))
            .filter(ProductEventModel.user_id.is_not(None))
            .group_by(ProductEventModel.event_name).all()
        }
        session_counts = dict(
            session.query(BetaSessionModel.user_id, func.count(BetaSessionModel.id))
            .group_by(BetaSessionModel.user_id).all()
        )
        user_events = {
            (user_id, event): int(count)
            for user_id, event, count in session.query(
                ProductEventModel.user_id,
                ProductEventModel.event_name,
                func.count(ProductEventModel.id),
            ).filter(ProductEventModel.user_id.is_not(None)).group_by(
                ProductEventModel.user_id,
                ProductEventModel.event_name,
            ).all()
        }
        feedback_counts = dict(
            session.query(BetaFeedbackModel.user_id, func.count(BetaFeedbackModel.id))
            .group_by(BetaFeedbackModel.user_id).all()
        )
    feedback = BetaFeedbackRepository.aggregate()
    issues = BetaIssueRepository.counts()
    beta_funnel = _funnel(event_counts)
    model = PredictionLedgerRepository.summary()
    testers = [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "cohort": user.beta_cohort,
            "is_active": bool(user.is_active),
            "created_at": user.created_at.isoformat() if user.created_at else "",
            "last_active_at": user.last_active_at.isoformat() if user.last_active_at else "",
            "sessions": int(session_counts.get(user.id, 0)),
            "analyses": int(user_events.get((user.id, "entry_analyzed"), 0)),
            "feedback": int(feedback_counts.get(user.id, 0)),
            "entries_saved": int(user_events.get((user.id, "entry_saved"), 0)),
            "entries_settled": int(user_events.get((user.id, "entry_settled"), 0)),
        }
        for user in users
    ]
    model_accuracy = model.get("projection_accuracy") or {}
    outcomes = _model_outcomes()
    return {
        "testers": len(users),
        "active_testers": sum(bool(user.is_active) for user in users),
        "active_this_week": sum(bool(user.last_active_at and user.last_active_at >= week_ago) for user in users),
        "new_testers": sum(bool(user.created_at and user.created_at >= week_ago) for user in users),
        "inactive_testers": sum(not bool(user.is_active) for user in users),
        "sessions": int(sessions),
        "analyses": int(event_counts.get("entry_analyzed", 0)),
        "recommendation_views": int(event_counts.get("recommendation_viewed", 0)),
        "recommendations_added": int(event_counts.get("recommendation_added", 0)),
        "entries_saved": int(event_counts.get("entry_saved", 0)),
        "entries_settled": int(event_counts.get("entry_settled", 0)),
        "feedback_responses": feedback["total_feedback"],
        "useful_rate": feedback["useful_rate"],
        "decision_change_rate": feedback["changed_decision_rate"],
        "bugs_reported": int(issues.get("BUG", 0)),
        "feature_requests": int(issues.get("FEATURE", 0)),
        "would_pay_distribution": feedback["would_pay_distribution"],
        "funnel": beta_funnel["funnel"],
        "conversion": beta_funnel["conversion"],
        "testers_activity": testers,
        "recent_feedback": BetaFeedbackRepository.recent(20),
        "recent_bugs": BetaIssueRepository.recent(20, "BUG"),
        "recent_feature_requests": BetaIssueRepository.recent(20, "FEATURE"),
        "segments": BetaFeedbackRepository.segments(),
        "model_performance": {
            "total_prediction_records": int(model.get("records", 0)),
            "versioned_prediction_records": int(model.get("versioned_records", 0)),
            "settled_unique_markets": int(model.get("settled_unique_markets", 0)),
            "verified_predictions": int(model_accuracy.get("verified_predictions", 0) or 0),
            "projection_mae": model_accuracy.get("mae"),
            "market_line_mae": model_accuracy.get("market_line_mae"),
            "bias": model_accuracy.get("bias"),
            "distribution_coverage": {
                "predictions": model_accuracy.get("distribution_predictions", 0),
                "middle_50": model_accuracy.get("middle_50_coverage"),
                "floor_ceiling": model_accuracy.get("floor_ceiling_coverage"),
            },
            **outcomes,
        },
    }


def _model_outcomes() -> dict:
    rows = PredictionLedgerRepository.evidence_rows()
    settled = [row for row in rows if row.get("result") in {"Win", "Loss", "Push"}]
    wins = sum(row["result"] == "Win" for row in settled)
    losses = sum(row["result"] == "Loss" for row in settled)
    pushes = sum(row["result"] == "Push" for row in settled)
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "recommendation_hit_rate": round((wins / (wins + losses)) * 100.0, 1) if wins + losses else 0.0,
    }


def _funnel(counts: dict[str, int]) -> dict:
    viewed = int(counts.get("recommendation_viewed", 0))
    saved = int(counts.get("entry_saved", 0))
    return {
        "funnel": [
            {"event": event, "count": int(counts.get(event, 0))}
            for event in ProductExperienceRepository.FUNNEL
        ],
        "conversion": {
            "view_to_analyze": _rate(counts.get("entry_analyzed", 0), viewed),
            "view_to_save": _rate(saved, viewed),
            "save_to_settle": _rate(counts.get("entry_settled", 0), saved),
        },
    }


def _rate(numerator: int, denominator: int) -> float:
    return round((int(numerator) / int(denominator)) * 100.0, 1) if denominator else 0.0
