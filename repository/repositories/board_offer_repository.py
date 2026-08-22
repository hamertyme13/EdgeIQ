from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import func

from analytics.prediction_evidence import offer_key
from repository.database import SessionLocal, initialize_database
from repository.models.board_offer_observation_model import BoardOfferObservationModel
from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.entity_normalization import canonical_person_key
from utils.stat_normalization import canonical_stat_label
from utils.time import utc_now


class BoardOfferRepository:
    """Captures the complete provider board independently of recommendations."""

    _schema_ready = False

    @staticmethod
    def _ensure_schema() -> None:
        if BoardOfferRepository._schema_ready:
            return
        initialize_database()
        BoardOfferRepository._schema_ready = True

    @staticmethod
    def record_many(rows: list[dict], provider: str, captured_at: datetime | None = None) -> int:
        if not rows:
            return 0
        BoardOfferRepository._ensure_schema()
        captured = captured_at or utc_now()
        bucket = captured.astimezone(UTC).replace(second=0, microsecond=0).isoformat()
        prepared = [_prepared_row(row, provider, bucket) for row in rows]
        prepared = [row for row in prepared if row is not None]
        if not prepared:
            return 0
        keys = [row["observation_key"] for row in prepared]
        market_keys = {row["market_key"] for row in prepared}
        with SessionLocal() as session:
            existing = {
                value for (value,) in session.query(BoardOfferObservationModel.observation_key)
                .filter(BoardOfferObservationModel.observation_key.in_(keys)).all()
            }
            opening_rows = (
                session.query(
                    BoardOfferObservationModel.market_key,
                    func.min(BoardOfferObservationModel.id),
                )
                .filter(BoardOfferObservationModel.market_key.in_(market_keys))
                .group_by(BoardOfferObservationModel.market_key)
                .all()
            )
            opening_ids = [row_id for _key, row_id in opening_rows]
            openings = {
                row.market_key: row.line
                for row in session.query(BoardOfferObservationModel)
                .filter(BoardOfferObservationModel.id.in_(opening_ids)).all()
            } if opening_ids else {}
            created = 0
            for row in prepared:
                if row["observation_key"] in existing:
                    continue
                row["opening_line"] = openings.get(row["market_key"], row["line"])
                session.add(BoardOfferObservationModel(**row, captured_at=captured))
                created += 1
            if created:
                session.commit()
            return created

    @staticmethod
    def attach_analysis(row: dict) -> bool:
        """Attach decision-time model evidence to the latest matching offer."""
        BoardOfferRepository._ensure_schema()
        key = offer_key(row)
        with SessionLocal() as session:
            observation = (
                session.query(BoardOfferObservationModel)
                .filter_by(offer_key=key)
                .order_by(BoardOfferObservationModel.captured_at.desc())
                .first()
            )
            if observation is None:
                # Standard pick'em offers are usually two-sided even when the
                # provider payload defaults to Over. Match the same exact line
                # before applying EdgeIQ's selected direction.
                observation = (
                    session.query(BoardOfferObservationModel)
                    .filter(
                        BoardOfferObservationModel.normalized_player_key
                        == canonical_person_key(row.get("player")),
                        BoardOfferObservationModel.sport
                        == str(row.get("sport") or row.get("league") or "").upper(),
                        BoardOfferObservationModel.stat == canonical_stat_label(row.get("stat")),
                        BoardOfferObservationModel.provider == str(row.get("platform") or ""),
                        BoardOfferObservationModel.line == float(row.get("line") or 0.0),
                        BoardOfferObservationModel.game == str(row.get("game") or ""),
                        BoardOfferObservationModel.scheduled_start == str(row.get("game_time") or ""),
                        BoardOfferObservationModel.offer_type
                        == str(row.get("line_offer_type") or "standard").lower(),
                    )
                    .order_by(BoardOfferObservationModel.captured_at.desc())
                    .first()
                )
            if observation is None:
                return False
            forecast = row.get("forecast_snapshot") or {}
            distribution = forecast.get("distribution") or {}
            observation.projection = _float_or_none(row.get("projection"))
            observation.probability = _float_or_none(row.get("confidence") or row.get("probability"))
            observation.expected_minutes = _float_or_none(distribution.get("expected_minutes"))
            observation.expected_opportunities = _float_or_none(distribution.get("expected_opportunities"))
            observation.model_version = str(row.get("model_version") or "")
            observation.feature_snapshot = json.dumps(forecast, default=str, sort_keys=True)
            observation.eligibility_status = "paid_eligible" if row.get("forecast_paid_eligible") else "paper_only"
            observation.eligibility_reason = str(forecast.get("reason") or "")
            observation.analyzed_at = utc_now()
            session.commit()
            return True

    @staticmethod
    def segment_evidence(sport: str, stat: str, provider: str) -> dict:
        BoardOfferRepository._ensure_schema()
        with SessionLocal() as session:
            total = (
                session.query(BoardOfferObservationModel.market_key)
                .filter(
                    BoardOfferObservationModel.sport == str(sport).upper(),
                    BoardOfferObservationModel.stat == canonical_stat_label(stat),
                    BoardOfferObservationModel.provider == provider,
                    BoardOfferObservationModel.outcome.in_(("Win", "Loss", "Push")),
                )
                .distinct().count()
            )
        maturity = "mature" if total >= 500 else "developing" if total >= 200 else "calibrating" if total >= 100 else "thin"
        return {
            "samples": total,
            "maturity": maturity,
            "paid_eligible": total >= 100,
            "next_threshold": 100 if total < 100 else 200 if total < 200 else 500 if total < 500 else total,
        }

    @staticmethod
    def settle_pending(limit: int = 500) -> dict:
        """Settle captured offers individually, including rejected markets."""
        BoardOfferRepository._ensure_schema()
        with SessionLocal() as session:
            rows = (
                session.query(BoardOfferObservationModel)
                .filter(BoardOfferObservationModel.outcome == "")
                .order_by(BoardOfferObservationModel.captured_at.asc())
                .limit(max(1, min(int(limit), 2000)))
                .all()
            )
            settled = 0
            unresolved = 0
            for row in rows:
                final = FinalStatsRepository.find_result({
                    "player": row.player,
                    "player_identity_id": row.player_identity_id,
                    "provider_player_id": row.provider_player_id,
                    "team": row.team,
                    "sport": row.sport,
                    "stat": row.stat,
                    "game": row.game,
                    "game_time": row.scheduled_start,
                    "platform": row.provider,
                })
                source = str((final or {}).get("source") or "").strip()
                if not final or source.lower() in {"", "unknown", "unmatched", "projection_estimate"}:
                    unresolved += 1
                    continue
                actual = float(final["actual"])
                row.actual = actual
                row.outcome_source = source
                row.outcome = "Push" if actual == row.line else (
                    "Win" if (actual > row.line) == (row.direction.lower() == "over") else "Loss"
                )
                if str(final.get("status") or "played").lower() == "dnp":
                    row.outcome = "Push"
                row.settled_at = utc_now()
                latest = (
                    session.query(BoardOfferObservationModel.line)
                    .filter_by(market_key=row.market_key)
                    .order_by(BoardOfferObservationModel.captured_at.desc())
                    .first()
                )
                row.closing_line = float(latest[0]) if latest else row.line
                settled += 1
            if settled:
                session.commit()
        return {"attempted": len(rows), "settled": settled, "unresolved": unresolved}

    @staticmethod
    def summary() -> dict:
        BoardOfferRepository._ensure_schema()
        with SessionLocal() as session:
            total = session.query(BoardOfferObservationModel).count()
            settled = session.query(BoardOfferObservationModel).filter(
                BoardOfferObservationModel.outcome.in_(("Win", "Loss", "Push"))
            ).count()
            analyzed = session.query(BoardOfferObservationModel).filter(
                BoardOfferObservationModel.analyzed_at.is_not(None)
            ).count()
            providers = dict(
                session.query(BoardOfferObservationModel.provider, func.count(BoardOfferObservationModel.id))
                .group_by(BoardOfferObservationModel.provider).all()
            )
        return {
            "observations": total,
            "analyzed": analyzed,
            "settled": settled,
            "rejected_or_unselected": max(0, total - analyzed),
            "providers": providers,
            "selection_bias_protection": True,
        }


def _prepared_row(raw: dict, provider: str, bucket: str) -> dict | None:
    player = str(raw.get("player") or raw.get("player_name") or "").strip()
    sport = str(raw.get("league") or raw.get("sport") or "").strip().upper()
    stat = canonical_stat_label(raw.get("stat") or "")
    if not player or not sport or not stat or raw.get("line") in (None, ""):
        return None
    payload = {
        **raw,
        "player": player,
        "sport": sport,
        "stat": stat,
        "platform": str(raw.get("platform") or provider),
        "direction": str(raw.get("direction") or "Over"),
    }
    market_parts = (
        canonical_person_key(player), sport, stat,
        str(payload.get("platform") or "").lower(),
        str(payload.get("game_id") or payload.get("event_id") or payload.get("game") or "").lower(),
        str(payload.get("game_time") or "")[:10],
        str(payload.get("direction") or "Over").lower(),
        str(payload.get("line_offer_type") or payload.get("odds_type") or "standard").lower(),
    )
    market = hashlib.sha256("|".join(market_parts).encode()).hexdigest()
    offer = offer_key(payload)
    observation = hashlib.sha256(f"{offer}|{float(raw['line']):.4f}|{bucket}".encode()).hexdigest()
    context = {
        key: raw.get(key) for key in (
            "injury_status", "lineup_status", "starter_status", "role", "position",
            "season_type", "home_away", "rest_days", "schedule_context",
        ) if raw.get(key) not in (None, "")
    }
    eligible = bool(raw.get("end_to_end_confirmed"))
    return {
        "observation_key": observation,
        "market_key": market,
        "offer_key": offer,
        "provider": str(raw.get("platform") or provider),
        "provider_offer_id": str(raw.get("provider_offer_id") or raw.get("projection_id") or raw.get("id") or ""),
        "provider_player_id": str(raw.get("provider_player_id") or raw.get("player_id") or ""),
        "player_identity_id": raw.get("player_identity_id"),
        "normalized_player_key": canonical_person_key(player),
        "player": player,
        "team": str(raw.get("team") or ""),
        "opponent": str(raw.get("opponent") or ""),
        "sport": sport,
        "stat": stat,
        "direction": str(raw.get("direction") or "Over"),
        "line": float(raw["line"]),
        "closing_line": None,
        "offer_type": str(raw.get("line_offer_type") or raw.get("odds_type") or "standard").lower(),
        "payout_multiplier": _float_or_none(raw.get("payout_multiplier") or raw.get("multiplier")),
        "game_id": str(raw.get("game_id") or raw.get("event_id") or ""),
        "game": str(raw.get("game") or ""),
        "scheduled_start": str(raw.get("game_time") or raw.get("scheduled_start") or ""),
        "home_away": str(raw.get("home_away") or ""),
        "rest_days": _float_or_none(raw.get("rest_days")),
        "context_snapshot": json.dumps(context, default=str, sort_keys=True),
        "provider_payload": json.dumps(raw, default=str, sort_keys=True),
        "eligibility_status": "trackable" if eligible else "unreviewed",
        "eligibility_reason": str(raw.get("eligibility_reason") or ""),
    }


def _float_or_none(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
