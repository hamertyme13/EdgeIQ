"""Immutable, deduplicated exact-line research quote snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from repository.database import SessionLocal, initialize_database
from repository.models.final_player_stat_model import FinalPlayerStatModel
from repository.models.market_quote_snapshot_model import MarketQuoteSnapshotModel
from utils.entity_normalization import canonical_person_key


class MarketQuoteRepository:
    @staticmethod
    def validation_inputs(*, limit: int = 500, final_limit: int = 20000) -> dict:
        """Read a bounded, recent quote cohort and same-day independent finals."""
        initialize_database()
        cutoff = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        quote_cap = max(1, min(limit, 500))
        final_cap = max(1, min(final_limit, 20000))
        with SessionLocal() as session:
            quotes = session.query(MarketQuoteSnapshotModel).filter(
                MarketQuoteSnapshotModel.captured_at >= cutoff,
            ).order_by(MarketQuoteSnapshotModel.captured_at.desc()).limit(quote_cap + 1).all()
            quote_rows = [{
                "player_key": row.player_key, "player": row.player, "platform": row.platform,
                "game": row.game, "game_time": row.game_time, "line": row.line,
                "captured_at": row.captured_at, "oldest_quote_at": row.oldest_quote_at,
                "market_event_id": row.market_event_id, "book_count": row.book_count,
                "market_over_probability": row.market_over_probability,
                "market_under_probability": row.market_under_probability,
                "model_over_probability": row.model_over_probability,
                "model_version": row.model_version,
            } for row in quotes[:quote_cap]]
            dates = set()
            for row in quote_rows:
                try:
                    start = datetime.fromisoformat(row["game_time"].replace("Z", "+00:00"))
                    if start.tzinfo is not None:
                        dates.add(start.astimezone(ZoneInfo("America/New_York")).date().isoformat())
                except ValueError:
                    continue
            finals = []
            truncated = False
            if dates:
                rows = session.query(FinalPlayerStatModel).filter(
                    FinalPlayerStatModel.sport == "NBA",
                    FinalPlayerStatModel.stat.in_(["Points", "PTS"]),
                    FinalPlayerStatModel.game_date.in_(dates),
                ).limit(final_cap + 1).all()
                truncated = len(rows) > final_cap
                finals = [{
                    "player": row.player, "game": row.game, "game_date": row.game_date,
                    "actual": row.actual, "source": row.source, "season_type": row.season_type,
                    "status": row.status,
                } for row in rows[:final_cap]]
        return {"quotes": quote_rows, "finals": finals, "finals_truncated": truncated,
                "quote_limit_reached": len(quotes) > quote_cap}

    @staticmethod
    def summary() -> dict:
        initialize_database()
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        with SessionLocal() as session:
            recent = session.query(func.count(MarketQuoteSnapshotModel.id)).filter(
                MarketQuoteSnapshotModel.captured_at >= cutoff,
            ).scalar()
            latest = session.query(func.max(MarketQuoteSnapshotModel.captured_at)).scalar()
        return {"captured_24h": int(recent or 0), "last_captured_at": latest,
                "collection_mode": "on_demand", "payout_verified": False}

    @staticmethod
    def record(offer: dict, market: dict, model_probability: float | None, model_version: str = "") -> dict:
        initialize_database()
        quote = {
            "event": market.get("event") or {},
            "books": market.get("books") or [],
            "over_probability": market["over_probability"],
            "under_probability": market["under_probability"],
            "oldest_update": market["oldest_update"],
            "book_count": market["book_count"],
            "source": market["source"],
            "source_type": market["source_type"],
        }
        identity = {
            "player_key": canonical_person_key(offer.get("player")),
            "platform": str(offer.get("platform") or ""),
            "provider_offer_id": str(offer.get("provider_offer_id") or offer.get("offer_id") or ""),
            "provider_event_id": str(offer.get("provider_event_id") or ""),
            "game_time": str(offer.get("game_time") or ""),
            "line": float(offer["line"]),
            "market_event_id": str(quote["event"]["event_id"]),
            "quote": quote,
            "model_probability": model_probability,
            "model_version": model_version,
        }
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
        captured_at = datetime.now(UTC).isoformat()
        with SessionLocal() as session:
            row = session.query(MarketQuoteSnapshotModel).filter_by(fingerprint=fingerprint).one_or_none()
            created = row is None
            if row is None:
                row = MarketQuoteSnapshotModel(
                    fingerprint=fingerprint,
                    captured_at=captured_at,
                    player_key=identity["player_key"],
                    player=str(offer.get("player") or ""),
                    platform=identity["platform"],
                    provider_offer_id=identity["provider_offer_id"],
                    provider_event_id=identity["provider_event_id"],
                    game=str(offer.get("game") or ""),
                    game_time=identity["game_time"],
                    line=identity["line"],
                    offer_type=str(offer.get("line_offer_type") or "standard"),
                    market_event_id=identity["market_event_id"],
                    oldest_quote_at=str(quote["oldest_update"]),
                    book_count=int(quote["book_count"]),
                    market_over_probability=float(quote["over_probability"]),
                    market_under_probability=float(quote["under_probability"]),
                    model_over_probability=model_probability,
                    model_version=model_version,
                    quote_payload=json.dumps(quote, sort_keys=True, default=str),
                )
                try:
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                except IntegrityError:
                    row = session.query(MarketQuoteSnapshotModel).filter_by(fingerprint=fingerprint).one()
                    created = False
            session.commit()
            return {"id": row.id, "captured_at": row.captured_at, "created": created}

    @staticmethod
    def history(player: str, platform: str, game: str, game_time: str, line: float, limit: int = 20) -> list[dict]:
        initialize_database()
        with SessionLocal() as session:
            rows = session.query(MarketQuoteSnapshotModel).filter_by(
                player_key=canonical_person_key(player), platform=platform,
                game=game, game_time=game_time, line=float(line),
            ).order_by(
                MarketQuoteSnapshotModel.captured_at.desc(), MarketQuoteSnapshotModel.id.desc(),
            ).limit(max(1, min(limit, 50))).all()
            return [
                {
                    "id": row.id,
                    "captured_at": row.captured_at,
                    "oldest_quote_at": row.oldest_quote_at,
                    "book_count": row.book_count,
                    "market_over_probability": row.market_over_probability,
                    "market_under_probability": row.market_under_probability,
                    "model_over_probability": row.model_over_probability,
                    "model_version": row.model_version,
                }
                for row in reversed(rows)
            ]
