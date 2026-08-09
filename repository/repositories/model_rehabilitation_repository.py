from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from analytics.grouped_validation import grouped_rolling_validation
from analytics.prediction_evidence import independent_market_key
from repository.database import SessionLocal, initialize_database
from repository.models.recommendation_snapshot_model import RecommendationSnapshotModel
from repository.models.shadow_prediction_model import ShadowPredictionModel
from repository.repositories.final_stats_repository import FinalStatsRepository
from repository.repositories.settings_repository import SettingsRepository
from utils.time import utc_now

VERIFIED_SOURCES_EXCLUDED = {"", "unknown", "unmatched", "projection_estimate", "integrity_quarantine"}


class ModelRehabilitationRepository:
    FEED_KEY = "canonical_recommendation_snapshot"
    SHADOW_KEY = "shadow_prediction_registry"
    _legacy_migrated = False

    @staticmethod
    def _migrate_legacy_registry() -> None:
        if ModelRehabilitationRepository._legacy_migrated:
            return
        initialize_database()
        legacy = _json(SettingsRepository.get(ModelRehabilitationRepository.SHADOW_KEY, ""), [])
        if legacy:
            grouped: dict[tuple[str, str], list[dict]] = {}
            for row in legacy:
                cohort = str(row.get("predicted_at") or "")[:10] or datetime.now(UTC).date().isoformat()
                version = str(row.get("model_version") or "legacy-shadow-v2.2")
                grouped.setdefault((cohort, version), []).append(row)
            for (cohort, version), rows in grouped.items():
                ModelRehabilitationRepository.queue_shadow(rows, model_version=version, target=len(rows), cohort_date=cohort)
            SettingsRepository.set(ModelRehabilitationRepository.SHADOW_KEY, "[]")
        ModelRehabilitationRepository._legacy_migrated = True

    @staticmethod
    def save_feed(payload: dict, *, model_version: str = "edgeiq-v2.2.1") -> dict:
        """Append an immutable snapshot and update the compatibility pointer."""
        initialize_database()
        current = ModelRehabilitationRepository.load_feed()
        merged = {**current, **payload}
        captured_at = utc_now()
        merged["captured_at"] = captured_at.isoformat()
        merged.pop("snapshot_id", None)
        feed = merged.get("feed") or {}
        platform = str(merged.get("platform") or feed.get("platform") or "All Platforms")
        sport = str(merged.get("sport") or feed.get("sport") or "All Sports")
        purpose = str(feed.get("purpose") or "recommendation_feed")
        snapshot_id = f"{captured_at.strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
        _stamp_snapshot_payload(merged, snapshot_id, model_version)
        with SessionLocal() as session:
            session.add(RecommendationSnapshotModel(
                snapshot_id=snapshot_id,
                model_version=model_version,
                platform=platform,
                sport=sport,
                purpose=purpose,
                captured_at=captured_at,
                payload=json.dumps(merged, default=str, sort_keys=True),
            ))
            session.commit()
        merged["snapshot_id"] = snapshot_id
        merged["model_version"] = model_version
        SettingsRepository.set(ModelRehabilitationRepository.FEED_KEY, json.dumps(merged, default=str))
        return merged

    @staticmethod
    def load_feed() -> dict:
        return _json(SettingsRepository.get(ModelRehabilitationRepository.FEED_KEY, ""), {})

    @staticmethod
    def snapshot_history(limit: int = 20) -> list[dict]:
        initialize_database()
        with SessionLocal() as session:
            rows = session.query(RecommendationSnapshotModel).order_by(
                RecommendationSnapshotModel.captured_at.desc()
            ).limit(max(1, min(limit, 200))).all()
            return [{
                "snapshot_id": row.snapshot_id,
                "model_version": row.model_version,
                "platform": row.platform,
                "sport": row.sport,
                "purpose": row.purpose,
                "captured_at": row.captured_at.isoformat() if row.captured_at else "",
                "payload": _json(row.payload, {}),
            } for row in rows]

    @staticmethod
    def queue_shadow(rows: list[dict], *, model_version: str, target: int = 227, cohort_date: str | None = None) -> dict:
        initialize_database()
        cohort = cohort_date or datetime.now(UTC).date().isoformat()
        created = 0
        with SessionLocal() as session:
            existing = {
                row[0] for row in session.query(ShadowPredictionModel.independent_market_key).filter_by(
                    cohort_date=cohort, model_version=model_version
                ).all()
            }
            needed = max(0, target - len(existing))
            for row in rows:
                key = independent_market_key(row)
                if not key or key in existing or row.get("line") is None:
                    continue
                session.add(ShadowPredictionModel(
                    cohort_date=cohort,
                    model_version=model_version,
                    independent_market_key=key,
                    player=str(row.get("player") or ""),
                    team=str(row.get("team") or ""),
                    sport=str(row.get("sport") or row.get("league") or "").upper(),
                    stat=str(row.get("stat") or ""),
                    direction=str(row.get("direction") or "Over"),
                    platform=str(row.get("platform") or ""),
                    game=str(row.get("game") or ""),
                    game_time=str(row.get("game_time") or ""),
                    line=float(row.get("line")),
                    projection=_float_or_none(row.get("projection")),
                    probability=float(row.get("confidence") or row.get("probability") or 50.0),
                    feature_snapshot=json.dumps(row, default=str, sort_keys=True),
                ))
                existing.add(key)
                created += 1
                if created >= needed:
                    break
            session.commit()
            queued = session.query(ShadowPredictionModel).filter_by(
                cohort_date=cohort, model_version=model_version
            ).count()
        return {
            "created": created,
            "queued": queued,
            "cohort_date": cohort,
            "remaining_target": max(0, target - queued),
            "message": "Shadow predictions do not count as evidence until verified final outcomes arrive.",
        }

    @staticmethod
    def settle_pending(limit: int = 500) -> dict:
        ModelRehabilitationRepository._migrate_legacy_registry()
        initialize_database()
        settled = failed = pending = 0
        with SessionLocal() as session:
            rows = session.query(ShadowPredictionModel).filter_by(status="shadow_pending").order_by(
                ShadowPredictionModel.game_time.asc(), ShadowPredictionModel.id.asc()
            ).limit(max(1, min(limit, 2000))).all()
            for row in rows:
                row.settlement_attempts += 1
                row.last_attempt_at = utc_now()
                match = FinalStatsRepository.find_result({
                    "player": row.player, "team": row.team, "sport": row.sport,
                    "stat": row.stat, "game": row.game, "game_time": row.game_time,
                    "platform": row.platform,
                })
                if not match or str(match.get("status") or "played").lower() == "live":
                    pending += 1
                    row.last_settlement_error = "Verified final stat is not available yet."
                    continue
                source = str(match.get("source") or "").strip()
                if source.lower() in VERIFIED_SOURCES_EXCLUDED:
                    failed += 1
                    row.last_settlement_error = "Final stat source is not eligible as verified evidence."
                    continue
                actual = float(match["actual"])
                status = str(match.get("status") or "played").lower()
                row.actual = actual
                row.outcome_source = source
                row.status = "Push" if actual == row.line else (
                    "Win" if (actual > row.line) == (row.direction.lower() == "over") else "Loss"
                )
                if status == "dnp":
                    row.status = "Push"
                row.settled_at = utc_now()
                row.last_settlement_error = ""
                settled += 1
            session.commit()
        result = {"settled": settled, "pending": pending, "failed": failed, "attempted": settled + pending + failed}
        SettingsRepository.set("shadow_settlement_status", json.dumps({**result, "ran_at": utc_now().isoformat()}))
        return result

    @staticmethod
    def reconcile_shadow(evidence_rows: list[dict]) -> int:
        """Compatibility reconciliation for verified ledger outcomes."""
        ModelRehabilitationRepository._migrate_legacy_registry()
        outcomes = {
            str(row.get("independent_market_key") or ""): row for row in evidence_rows
            if row.get("result") in {"Win", "Loss", "Push"}
            and str(row.get("outcome_source") or "").strip().lower() not in VERIFIED_SOURCES_EXCLUDED
        }
        updated = 0
        with SessionLocal() as session:
            for row in session.query(ShadowPredictionModel).filter_by(status="shadow_pending").all():
                outcome = outcomes.get(row.independent_market_key)
                if not outcome:
                    continue
                row.status = outcome["result"]
                row.actual = outcome.get("actual")
                row.outcome_source = str(outcome.get("outcome_source") or "")
                row.settled_at = utc_now()
                row.last_settlement_error = ""
                updated += 1
            session.commit()
        return updated

    @staticmethod
    def shadow_rows() -> list[dict]:
        ModelRehabilitationRepository._migrate_legacy_registry()
        with SessionLocal() as session:
            rows = session.query(ShadowPredictionModel).order_by(ShadowPredictionModel.predicted_at.asc()).all()
            return [_shadow_dict(row) for row in rows]

    @staticmethod
    def shadow_status(evidence_rows: list[dict] | None = None, validation: dict | None = None) -> dict:
        if evidence_rows is not None:
            ModelRehabilitationRepository.reconcile_shadow(evidence_rows)
        rows = ModelRehabilitationRepository.shadow_rows()
        settled = [row for row in rows if row["result"] in {"Win", "Loss", "Push"}]
        decisions = [row for row in settled if row["result"] in {"Win", "Loss"}]
        wins = sum(row["result"] == "Win" for row in decisions)
        grouped = grouped_rolling_validation(rows, minimum_train=50, minimum_predictions=30)
        segments = {(row["sport"], row["stat"], row["platform"]) for row in decisions}
        validation = validation or {}
        gates = {
            "minimum_settled": len(decisions) >= 100,
            "minimum_accuracy": bool(decisions) and wins / len(decisions) >= 0.55,
            "brier_and_calibration": bool(grouped.get("ready") and grouped.get("passed")),
            "closing_line_value": bool((validation.get("closing_line_value") or {}).get("tracked_legs", 0) >= 50),
            "chronological_holdout": bool((validation.get("holdout") or {}).get("ready") and (validation.get("holdout") or {}).get("passed")),
            "segment_coverage": len(segments) >= 5 and len({row["sport"] for row in decisions}) >= 2,
            "verified_outcomes": all(row.get("outcome_source") for row in settled),
        }
        failures = sum(
            1 for row in rows
            if row.get("last_settlement_error")
            and row.get("settlement_attempts", 0) >= 3
            and _past_settlement_window(row.get("game_time"))
        )
        return {
            "queued": len(rows), "settled": len(settled), "cohorts": len({row["cohort_date"] for row in rows}),
            "accuracy": round(wins / len(decisions) * 100.0, 1) if decisions else 0.0,
            "release_ready": all(gates.values()), "mode": "review" if all(gates.values()) else "shadow",
            "release_requirements": gates, "grouped_validation": grouped,
            "settlement_failures": failures,
        }


def _shadow_dict(row: ShadowPredictionModel) -> dict:
    return {
        "id": row.id, "cohort_date": row.cohort_date, "model_version": row.model_version,
        "independent_market_key": row.independent_market_key, "player": row.player, "team": row.team,
        "sport": row.sport, "stat": row.stat, "direction": row.direction, "platform": row.platform,
        "game": row.game, "game_time": row.game_time, "line": row.line, "projection": row.projection,
        "probability": row.probability, "result": row.status if row.status != "shadow_pending" else "",
        "actual": row.actual, "outcome_source": row.outcome_source, "settlement_attempts": row.settlement_attempts,
        "last_settlement_error": row.last_settlement_error, "predicted_at": row.predicted_at,
        "settled_at": row.settled_at,
    }


def _stamp_snapshot_payload(payload: dict, snapshot_id: str, model_version: str) -> None:
    payload["snapshot_id"] = snapshot_id
    payload["model_version"] = model_version
    for key in ("daily_briefing", "opportunity_feed"):
        recommendation = payload.get(key)
        if not isinstance(recommendation, dict):
            continue
        recommendation["recommendation_snapshot_id"] = snapshot_id
        recommendation["model_version"] = model_version
        groups = [recommendation.get("opportunities") or [], recommendation.get("top_opportunities") or [], recommendation.get("suggested_entries") or []]
        groups.extend((recommendation.get("sections") or {}).get(section) or [] for section in ("bet", "paper", "watch", "avoid"))
        for group in groups:
            for row in group:
                if isinstance(row, dict):
                    row["recommendation_snapshot_id"] = snapshot_id
                    row["model_version"] = model_version


def _float_or_none(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _past_settlement_window(value: object) -> bool:
    try:
        game_time = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if game_time.tzinfo is None:
            game_time = game_time.replace(tzinfo=UTC)
        return datetime.now(UTC) >= game_time.astimezone(UTC) + timedelta(hours=12)
    except (TypeError, ValueError):
        return False


def _json(value: str, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default
