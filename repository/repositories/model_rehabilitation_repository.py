from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import time
import uuid
import zlib
from collections import Counter
from contextlib import suppress
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from analytics.grouped_validation import grouped_rolling_validation
from analytics.model_registry import PRODUCT_MODEL_VERSION
from analytics.prediction_evidence import independent_market_key
from repository.database import SessionLocal, initialize_database
from repository.models.recommendation_snapshot_model import RecommendationSnapshotModel
from repository.models.shadow_prediction_model import ShadowPredictionModel
from repository.repositories.final_stats_repository import FinalStatsRepository
from repository.repositories.leg_recommendation_snapshot_repository import LegRecommendationSnapshotRepository
from repository.repositories.provider_offer_snapshot_repository import ProviderOfferSnapshotRepository
from repository.repositories.settings_repository import SettingsRepository
from services.recommendation_snapshot import attach_leg_recommendations, attach_offer_snapshots, stamp_snapshot_payload
from utils.entity_normalization import canonical_person_key
from utils.time import utc_now

VERIFIED_SOURCES_EXCLUDED = {"", "unknown", "unmatched", "projection_estimate", "integrity_quarantine"}
SNAPSHOT_COMPRESSION_PREFIX = "zlib64:"
_log = logging.getLogger(__name__)


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
    def save_feed(payload: dict, *, model_version: str = PRODUCT_MODEL_VERSION) -> dict:
        """Append an immutable snapshot and update the compatibility pointer."""
        started = time.monotonic()
        stage_started = started

        def record_stage(name: str) -> None:
            nonlocal stage_started
            elapsed_ms = (time.monotonic() - stage_started) * 1000
            if elapsed_ms >= 1000:
                _log.warning("Recommendation snapshot %s took %.1f ms", name, elapsed_ms)
            stage_started = time.monotonic()

        initialize_database()
        current = ModelRehabilitationRepository.load_feed()
        merged = deepcopy({**current, **payload})
        captured_at = utc_now()
        merged["captured_at"] = captured_at.isoformat()
        merged.pop("snapshot_id", None)
        feed = merged.get("feed") or {}
        platform = str(payload.get("platform") or feed.get("platform") or "All Platforms")
        sport = str(payload.get("sport") or feed.get("sport") or "All Sports")
        purpose = str(feed.get("purpose") or "recommendation_feed")
        snapshot_id = f"{captured_at.strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
        stamp_snapshot_payload(merged, snapshot_id, model_version, captured_at, updated_sections=set(payload))
        record_stage("prepare")
        attach_offer_snapshots(merged, set(payload), ProviderOfferSnapshotRepository.capture_many)
        record_stage("offer_capture")
        attach_leg_recommendations(
            merged, set(payload),
            lambda rows: LegRecommendationSnapshotRepository.capture(
                rows, feed_snapshot_id=snapshot_id, model_version=model_version,
                captured_at=captured_at.replace(tzinfo=UTC),
            ),
        )
        record_stage("leg_capture")
        with SessionLocal() as session:
            session.add(RecommendationSnapshotModel(
                snapshot_id=snapshot_id,
                model_version=model_version,
                platform=platform,
                sport=sport,
                purpose=purpose,
                captured_at=captured_at,
                payload=_encode_snapshot_payload(merged),
            ))
            session.commit()
        record_stage("immutable_insert")
        snapshot_props = _snapshot_props({key: merged[key] for key in payload})
        evidence_capture = ModelRehabilitationRepository.queue_shadow(
            snapshot_props,
            model_version=model_version,
            target=None,
            cohort_date=captured_at.date().isoformat(),
        ) if snapshot_props else {"created": 0, "queued": 0}
        record_stage("shadow_queue")
        merged["evidence_capture"] = {
            "eligible_props": len(snapshot_props),
            "created": int(evidence_capture.get("created") or 0),
            "queued": int(evidence_capture.get("queued") or 0),
        }
        merged["snapshot_id"] = snapshot_id
        merged["model_version"] = model_version
        SettingsRepository.set(ModelRehabilitationRepository.FEED_KEY, snapshot_id)
        record_stage("pointer_write")
        if "daily_briefing" in payload:
            briefing = merged.get("daily_briefing") or {}
            for provider in {briefing.get("platform"), briefing.get("requested_platform")} - {None, ""}:
                SettingsRepository.set(_daily_feed_key(str(provider), briefing.get("sport")), snapshot_id)
        record_stage("daily_pointer_write")
        return merged

    @staticmethod
    def load_feed() -> dict:
        pointer = SettingsRepository.get(ModelRehabilitationRepository.FEED_KEY, "")
        if not pointer:
            return {}
        if pointer.startswith("{"):
            return _json(pointer, {})
        return ModelRehabilitationRepository.get_snapshot(pointer) or {}

    @staticmethod
    def load_daily_feed(platform: str, sport: str | None) -> dict:
        """Resolve a scope-specific pointer through the indexed immutable snapshot ID."""
        snapshot_id = SettingsRepository.get(_daily_feed_key(platform, sport), "")
        if not snapshot_id:
            return ModelRehabilitationRepository.load_feed()
        with SessionLocal() as session:
            row = session.query(RecommendationSnapshotModel).filter_by(snapshot_id=snapshot_id).first()
            return _decode_snapshot_payload(row.payload) if row else {}

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
                "payload": _decode_snapshot_payload(row.payload),
            } for row in rows]

    @staticmethod
    def get_snapshot(snapshot_id: str) -> dict | None:
        if not snapshot_id:
            return None
        with SessionLocal() as session:
            row = session.query(RecommendationSnapshotModel).filter_by(snapshot_id=snapshot_id).first()
            return _decode_snapshot_payload(row.payload) if row else None

    @staticmethod
    def queue_shadow(
        rows: list[dict],
        *,
        model_version: str,
        target: int | None = 227,
        cohort_date: str | None = None,
    ) -> dict:
        initialize_database()
        cohort = cohort_date or datetime.now(UTC).date().isoformat()
        created = 0
        with SessionLocal() as session:
            existing = {
                row[0] for row in session.query(ShadowPredictionModel.independent_market_key).filter_by(
                    cohort_date=cohort, model_version=model_version
                ).all()
            }
            needed = len(rows) if target is None else max(0, target - len(existing))
            candidates = []
            for row in rows if needed else []:
                key = independent_market_key(row)
                if not key or key in existing or row.get("line") is None:
                    continue
                candidates.append({
                    "cohort_date": cohort, "model_version": model_version,
                    "predicted_at": datetime.now(UTC).replace(tzinfo=None),
                    "independent_market_key": key,
                    "player": str(row.get("player") or ""),
                    "team": str(row.get("team") or ""),
                    "sport": str(row.get("sport") or row.get("league") or "").upper(),
                    "stat": str(row.get("stat") or ""),
                    "direction": str(row.get("direction") or "Over"),
                    "platform": str(row.get("platform") or ""),
                    "game": str(row.get("game") or ""),
                    "game_time": str(row.get("game_time") or ""),
                    "line": float(str(row["line"])),
                    "projection": _float_or_none(row.get("projection")),
                    "probability": float(row.get("confidence") or row.get("probability") or 50.0),
                    "feature_snapshot": json.dumps(row, default=str, sort_keys=True),
                })
                existing.add(key)
                if len(candidates) >= needed:
                    break
            dialect = session.bind.dialect.name
            if candidates and dialect in {"sqlite", "postgresql"}:
                insert = sqlite_insert if dialect == "sqlite" else postgres_insert
                for offset in range(0, len(candidates), 100):
                    statement = insert(ShadowPredictionModel).values(candidates[offset:offset + 100])
                    result = session.execute(statement.on_conflict_do_nothing(
                        index_elements=["cohort_date", "model_version", "independent_market_key"]
                    ))
                    created += max(0, result.rowcount)
            else:
                for candidate in candidates:
                    try:
                        with session.begin_nested():
                            session.add(ShadowPredictionModel(**candidate))
                            session.flush()
                        created += 1
                    except IntegrityError:
                        continue
            session.commit()
            queued = session.query(ShadowPredictionModel).filter_by(
                cohort_date=cohort, model_version=model_version
            ).count()
        return {
            "created": created,
            "queued": queued,
            "cohort_date": cohort,
            "remaining_target": max(0, target - queued) if target is not None else 0,
            "message": "Shadow predictions do not count as evidence until verified final outcomes arrive.",
        }

    @staticmethod
    def settle_pending(limit: int = 500, *, model_version_prefix: str = "") -> dict:
        ModelRehabilitationRepository._migrate_legacy_registry()
        initialize_database()
        reconciled = 0
        if not model_version_prefix:
            from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository

            reconciled = ModelRehabilitationRepository.reconcile_shadow(
                PredictionLedgerRepository.evidence_rows(include_legacy=False)
            )
        settled = failed = pending = excluded = 0
        with SessionLocal() as session:
            query = session.query(ShadowPredictionModel).filter_by(status="shadow_pending")
            if model_version_prefix:
                query = query.filter(ShadowPredictionModel.model_version.like(f"{model_version_prefix}%"))
            ordered = query.order_by(
                ShadowPredictionModel.last_attempt_at.asc().nullsfirst(),
                ShadowPredictionModel.game_time.asc(), ShadowPredictionModel.id.asc()
            )
            batch_size = max(1, min(limit, 2000))
            deferred_future = 0
            if model_version_prefix == "nba-points-board/":
                # Read only identifiers and times while searching past future games.
                candidates = ordered.with_entities(
                    ShadowPredictionModel.id, ShadowPredictionModel.game_time,
                ).limit(20_000).all()
                due_ids = []
                for row_id, game_time in candidates:
                    if _past_game_completion_window(game_time):
                        due_ids.append(row_id)
                        if len(due_ids) >= batch_size:
                            break
                    else:
                        deferred_future += 1
                by_id = {row.id: row for row in query.filter(ShadowPredictionModel.id.in_(due_ids)).all()}
                rows = [by_id[row_id] for row_id in due_ids if row_id in by_id]
            else:
                rows = ordered.limit(batch_size).all()
            for row in rows:
                if row.model_version.startswith("nba-points-board/"):
                    game_teams = [part.strip().upper() for part in str(row.game or "").split("@")]
                    team = str(row.team or "").strip().upper()
                    if " + " in row.player or (team and len(game_teams) == 2 and team not in game_teams):
                        row.status = "shadow_excluded"
                        row.last_attempt_at = utc_now()
                        row.last_settlement_error = "Not an individual NBA Points offer with a matching game team."
                        excluded += 1
                        continue
                if not _past_game_completion_window(row.game_time):
                    pending += 1
                    row.last_attempt_at = utc_now()
                    row.last_settlement_error = "Waiting for the game and official stat correction window to finish."
                    continue
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
        result = {
            "settled": settled, "reconciled_from_ledger": reconciled,
            "pending": pending, "failed": failed, "excluded": excluded,
            "deferred_future": deferred_future,
            "attempted": settled + pending + failed + excluded,
        }
        status_key = "nba_points_shadow_settlement_status" if model_version_prefix else "shadow_settlement_status"
        SettingsRepository.set(status_key, json.dumps({**result, "ran_at": utc_now().isoformat()}))
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
    def nba_points_board_validation_rows(limit: int = 5000) -> list[dict]:
        """Read settled prospective board forecasts for strict pregame evaluation."""
        initialize_database()
        with SessionLocal() as session:
            rows = (
                session.query(ShadowPredictionModel)
                .filter(
                    ShadowPredictionModel.sport == "NBA",
                    ShadowPredictionModel.stat.in_(("Points", "PTS")),
                    ShadowPredictionModel.model_version.like("nba-points-board/%"),
                    ShadowPredictionModel.status.in_(("Win", "Loss", "Push")),
                )
                .order_by(ShadowPredictionModel.predicted_at.desc(), ShadowPredictionModel.id.desc())
                .limit(max(1, min(int(limit), 5000)))
                .all()
            )
            evidence = []
            for row in rows:
                payload = _json(row.feature_snapshot, {})
                snapshot = payload.get("forecast_snapshot") if isinstance(payload, dict) else None
                evidence.append({
                    "id": row.id,
                    "independent_market_key": row.independent_market_key,
                    "player": row.player,
                    "team": row.team,
                    "game": row.game,
                    "sport": row.sport,
                    "stat": row.stat,
                    "platform": row.platform,
                    "line": row.line,
                    "direction": row.direction,
                    "projection": row.projection,
                    "probability": row.probability,
                    "model_version": row.model_version,
                    "feature_snapshot": snapshot,
                    "feature_as_of": snapshot.get("feature_as_of") if isinstance(snapshot, dict) else None,
                    "predicted_at": row.predicted_at,
                    "game_time": row.game_time,
                    "settled_at": row.settled_at,
                    "result": row.status,
                    "actual": row.actual,
                    "outcome_source": row.outcome_source,
                    "evidence_origin": "prospective_board",
                })
            return evidence

    @staticmethod
    def nba_points_board_captured_player_games(cohort_date: str) -> set[tuple[str, str]]:
        """Identify player-games already locked in this day's prospective board cohort."""
        initialize_database()
        with SessionLocal() as session:
            rows = session.query(
                ShadowPredictionModel.player, ShadowPredictionModel.game_time,
            ).filter(
                ShadowPredictionModel.cohort_date == cohort_date,
                ShadowPredictionModel.model_version.like("nba-points-board/%"),
            ).all()
        return {(canonical_person_key(player), str(game_time or "")) for player, game_time in rows}

    @staticmethod
    def nba_points_board_cohort_summary(cohort_date: str) -> dict:
        """Report persisted pregame forecasts, not only the latest retry's inserts."""
        initialize_database()
        with SessionLocal() as session:
            snapshots = session.query(
                ShadowPredictionModel.feature_snapshot,
                ShadowPredictionModel.predicted_at,
                ShadowPredictionModel.game_time,
            ).filter(
                ShadowPredictionModel.cohort_date == cohort_date,
                ShadowPredictionModel.model_version.like("nba-points-board/%"),
            ).all()
        sources: dict[str, int] = {}
        challenger_statuses = {"minutes": Counter(), "shot_volume": Counter()}
        market_prior_games: Counter[int] = Counter()
        lock_statuses: Counter[str] = Counter()
        qualified_pregame_locks = 0
        for payload_text, predicted_at, game_time in snapshots:
            payload = _json(payload_text, {})
            forecast = payload.get("forecast_snapshot") or {}
            source = str(forecast.get("source") or "unknown") if isinstance(forecast, dict) else "unknown"
            sources[source] = sources.get(source, 0) + 1
            features = forecast.get("features") or {} if isinstance(forecast, dict) else {}
            if not isinstance(features, dict):
                features = {}
            provenance = features.get("nba_points_history_provenance") or {}
            if not isinstance(provenance, dict):
                provenance = {}
            try:
                feature_at = datetime.fromisoformat(str(forecast["feature_as_of"]).replace("Z", "+00:00"))
                game_at = datetime.fromisoformat(str(game_time).replace("Z", "+00:00"))
                predicted = predicted_at.replace(tzinfo=UTC) if predicted_at.tzinfo is None else predicted_at
                feature_at = feature_at.replace(tzinfo=UTC) if feature_at.tzinfo is None else feature_at
                game_at = game_at.replace(tzinfo=UTC) if game_at.tzinfo is None else game_at
                status = "pregame_locked" if feature_at <= predicted < game_at else "invalid_lock_order"
            except (KeyError, TypeError, ValueError, AttributeError):
                status = "missing_lock_time"
            if status == "pregame_locked" and provenance.get("status") != "verified":
                status = "history_provenance_unverified"
            lock_statuses[status] += 1
            if status == "pregame_locked" and source == "verified_history_distribution":
                qualified_pregame_locks += 1
            for name, key in (("minutes", "nba_points_minutes_shadow"),
                              ("shot_volume", "nba_points_shot_volume_shadow")):
                evidence = features.get(key)
                status = str(evidence.get("status") or "not_recorded") if isinstance(evidence, dict) else "not_recorded"
                challenger_statuses[name][status] += 1
            if source == "market_prior":
                with suppress(TypeError, ValueError):
                    market_prior_games[int(features.get("verified_games") or 0)] += 1
        return {
            "captured_total": len(snapshots),
            "qualified_forecasts_total": sources.get("verified_history_distribution", 0),
            "pregame_verified_locks_total": lock_statuses.get("pregame_locked", 0),
            "qualified_pregame_locks_total": qualified_pregame_locks,
            "lock_statuses_total": dict(sorted(lock_statuses.items())),
            "forecast_sources_total": dict(sorted(sources.items())),
            "challenger_statuses_total": {
                name: dict(sorted(statuses.items())) for name, statuses in challenger_statuses.items()
            },
            "market_prior_verified_game_counts_total": dict(sorted(market_prior_games.items())),
        }

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
            if row.get("result") != "shadow_excluded"
            and row.get("last_settlement_error")
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


def _daily_feed_key(platform: str, sport: str | None) -> str:
    scope = json.dumps([platform.strip().casefold(), str(sport or "All Sports").strip().casefold()])
    return "daily_snapshot_scope:" + hashlib.sha256(scope.encode()).hexdigest()


def _snapshot_props(payload: object) -> list[dict]:
    """Collect each independently settleable prop embedded in a recommendation snapshot."""
    selected: dict[str, dict] = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if (
                value.get("player")
                and value.get("stat")
                and value.get("line") is not None
                and value.get("game_time")
                and value.get("platform")
            ):
                key = independent_market_key(value)
                selected.setdefault(key, dict(value))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return list(selected.values())


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


def _past_game_completion_window(value: object) -> bool:
    try:
        game_time = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if game_time.tzinfo is None:
            game_time = game_time.replace(tzinfo=UTC)
        return datetime.now(UTC) >= game_time.astimezone(UTC) + timedelta(hours=4)
    except (TypeError, ValueError):
        return True


def _json(value: str, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default


def _encode_snapshot_payload(payload: dict) -> str:
    serialized = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")
    return SNAPSHOT_COMPRESSION_PREFIX + base64.b64encode(zlib.compress(serialized, level=6)).decode("ascii")


def _decode_snapshot_payload(value: str) -> dict:
    if not value.startswith(SNAPSHOT_COMPRESSION_PREFIX):
        return _json(value, {})
    try:
        compressed = base64.b64decode(value[len(SNAPSHOT_COMPRESSION_PREFIX):], validate=True)
        return _json(zlib.decompress(compressed).decode("utf-8"), {})
    except (ValueError, UnicodeError, binascii.Error, zlib.error) as exc:
        _log.warning("A stored recommendation snapshot could not be decoded: %s", exc)
        return {}
