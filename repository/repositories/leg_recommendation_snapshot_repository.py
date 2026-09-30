"""Immutable per-leg recommendation evidence linked to a feed and exact offer."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from repository import database
from repository.models.board_offer_observation_model import BoardOfferObservationModel
from repository.models.leg_recommendation_snapshot_model import LegRecommendationSnapshotModel
from services.market_baseline import capture_market_baseline


def _number(value: object) -> float | None:
    try:
        number = float(str(value)) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number is not None and math.isfinite(number) else None


def _evidence(row: dict, feed_snapshot_id: str, model_version: str, captured_at: datetime) -> dict | None:
    if not row.get("offer_snapshot_id") or not row.get("player") or not row.get("stat"):
        return None
    line = _number(row.get("line"))
    if line is None:
        return None
    projection = _number(row.get("projection"))
    confidence = _number(row.get("confidence"))
    if projection is None and confidence is None:
        return None
    market_baseline, market_baseline_exclusion = capture_market_baseline(row, captured_at)
    return {
        "feed_snapshot_id": feed_snapshot_id,
        "offer_snapshot_id": str(row["offer_snapshot_id"]),
        "model_version": model_version,
        "scoring_version": str(row.get("scoring_version") or ""),
        "player": str(row["player"]),
        "sport": str(row.get("sport") or ""),
        "game": str(row.get("game") or ""),
        "stat": str(row["stat"]),
        "direction": str(row.get("direction") or "Over"),
        "line": line,
        "projection": projection,
        "confidence": confidence,
        "calibrated_confidence": _number(row.get("calibrated_confidence")),
        "edgeiq_score": _number(row.get("edgeiq_score")),
        "feature_as_of": str(row.get("feature_as_of") or ""),
        "projection_source": str(row.get("projection_source") or ""),
        "data_quality": row.get("data_quality") if isinstance(row.get("data_quality"), dict) else {},
        "grade": str(row.get("grade") or ""),
        "market_baseline": market_baseline,
        "market_baseline_exclusion": market_baseline_exclusion,
    }


class LegRecommendationSnapshotRepository:
    @staticmethod
    def capture(
        rows: list[dict], *, feed_snapshot_id: str, model_version: str,
        captured_at: datetime | None = None,
    ) -> None:
        if not rows:
            return
        database.initialize_database()
        recorded_at = captured_at or datetime.now(UTC)
        seen: set[str] = set()
        with database.SessionLocal() as session:
            for row in rows:
                evidence = _evidence(row, feed_snapshot_id, model_version, recorded_at)
                if evidence is None:
                    continue
                serialized = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
                snapshot_id = hashlib.sha256(serialized.encode()).hexdigest()
                row["leg_recommendation_snapshot_id"] = snapshot_id
                if snapshot_id in seen:
                    continue
                seen.add(snapshot_id)
                record = LegRecommendationSnapshotModel(
                    snapshot_id=snapshot_id,
                    feed_snapshot_id=feed_snapshot_id,
                    offer_snapshot_id=evidence["offer_snapshot_id"],
                    model_version=model_version,
                    player=evidence["player"], sport=evidence["sport"], stat=evidence["stat"],
                    direction=evidence["direction"], line=evidence["line"],
                    projection=evidence["projection"], confidence=evidence["confidence"],
                    feature_as_of=evidence["feature_as_of"], evidence=serialized,
                )
                try:
                    with session.begin_nested():
                        session.add(record)
                        session.flush()
                except IntegrityError:
                    pass
            session.commit()

    @staticmethod
    def get(snapshot_id: str) -> dict | None:
        if not snapshot_id:
            return None
        database.initialize_database()
        with database.SessionLocal() as session:
            row = session.query(LegRecommendationSnapshotModel).filter_by(snapshot_id=snapshot_id).first()
            return json.loads(str(row.evidence)) if row else None

    @staticmethod
    def settled_linked_rows(limit: int = 5000) -> dict:
        """Read one settled board observation per offer without changing outcomes."""
        database.initialize_database()
        bound = max(1, min(int(limit), 10000))
        with database.SessionLocal() as session:
            latest = (
                session.query(func.max(BoardOfferObservationModel.id).label("id"))
                .filter(
                    BoardOfferObservationModel.offer_snapshot_id != "",
                    BoardOfferObservationModel.outcome.in_(("Win", "Loss", "Push")),
                    BoardOfferObservationModel.final_game_date != "",
                )
                .group_by(BoardOfferObservationModel.offer_snapshot_id)
                .subquery()
            )
            records = (
                session.query(LegRecommendationSnapshotModel, BoardOfferObservationModel)
                .join(
                    BoardOfferObservationModel,
                    LegRecommendationSnapshotModel.offer_snapshot_id == BoardOfferObservationModel.offer_snapshot_id,
                )
                .join(latest, BoardOfferObservationModel.id == latest.c.id)
                .order_by(BoardOfferObservationModel.scheduled_start.asc(), LegRecommendationSnapshotModel.id.asc())
                .limit(bound + 1)
                .all()
            )
            total_board = session.query(func.count()).select_from(latest).scalar() or 0
            rows = []
            for leg, board in records[:bound]:
                evidence = json.loads(str(leg.evidence))
                rows.append({
                    **evidence,
                    "snapshot_id": leg.snapshot_id,
                    "created_at": leg.created_at.isoformat() if leg.created_at else "",
                    "game_start": board.scheduled_start,
                    "actual": board.actual,
                    "board_outcome": board.outcome,
                    "outcome_source": board.outcome_source,
                    "final_game_date": board.final_game_date,
                    "provider": board.provider,
                    "player_key": board.normalized_player_key,
                })
            return {"rows": rows, "settled_board_offers": int(total_board), "truncated": len(records) > bound}
