from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from statistics import mean

from sqlalchemy.exc import IntegrityError

from repository.database import SessionLocal, initialize_database
from repository.models.player_feature_model import PlayerFeatureModel
from repository.repositories.final_stats_repository import FinalStatsRepository
from repository.repositories.player_identity_repository import PlayerIdentityRepository
from utils.entity_normalization import canonical_person_key
from utils.stat_normalization import canonical_stat_label

_log = logging.getLogger(__name__)


class PlayerFeatureRepository:
    _schema_ready = False

    @staticmethod
    def _ensure_schema() -> None:
        if not PlayerFeatureRepository._schema_ready:
            initialize_database()
            PlayerFeatureRepository._schema_ready = True

    @staticmethod
    def feature_key(player: object, sport: object, stat: object) -> str:
        return "|".join((
            canonical_person_key(player),
            str(sport or "").upper(),
            canonical_stat_label(stat).lower(),
        ))

    @staticmethod
    def get(player: str, sport: str, stat: str) -> dict | None:
        PlayerFeatureRepository._ensure_schema()
        key = PlayerFeatureRepository.feature_key(player, sport, stat)
        with SessionLocal() as session:
            row = session.query(PlayerFeatureModel).filter_by(feature_key=key).first()
            return _serialize(row) if row else None

    @staticmethod
    def history(
        player: str,
        sport: str,
        stat: str,
        *,
        team: str = "",
        limit: int = 100,
        max_age_hours: float = 12.0,
        refresh: bool = False,
        materialize_missing: bool = True,
    ) -> list[dict]:
        cached = PlayerFeatureRepository.get(player, sport, stat)
        if cached and not refresh and _is_fresh(cached["materialized_at"], max_age_hours):
            return list(cached["history"])[:limit]
        if not materialize_missing:
            return []
        materialized = PlayerFeatureRepository.materialize(player, sport, stat, team=team, limit=max(limit, 100))
        return list(materialized["history"])[:limit]

    @staticmethod
    def materialize(player: str, sport: str, stat: str, *, team: str = "", limit: int = 120) -> dict:
        PlayerFeatureRepository._ensure_schema()
        history = FinalStatsRepository.history(
            player,
            stat,
            sport=sport,
            limit=limit,
            team=team,
            include_opportunity_context=True,
        )
        identity = PlayerIdentityRepository.resolve(player, sport, team, create=False)
        summary = _history_summary(history)
        key = PlayerFeatureRepository.feature_key(player, sport, stat)
        now = datetime.now(UTC)
        source_updated_at = max((str(row.get("game_date") or "") for row in history), default="")
        values = {
            "player_identity_id": (identity or {}).get("id"),
            "normalized_player_key": canonical_person_key(player),
            "player": player,
            "team": team,
            "sport": str(sport or "").upper(),
            "stat": canonical_stat_label(stat),
            "sample_size": len(history),
            "history_json": json.dumps(history, default=str, sort_keys=True),
            "summary_json": json.dumps(summary, default=str, sort_keys=True),
            "source_updated_at": source_updated_at,
            "materialized_at": now,
        }
        for attempt in range(2):
            with SessionLocal() as session:
                row = session.query(PlayerFeatureModel).filter_by(feature_key=key).first()
                if row is None:
                    row = PlayerFeatureModel(feature_key=key)
                    session.add(row)
                for field, value in values.items():
                    setattr(row, field, value)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    if attempt == 0:
                        continue
                    raise
                session.refresh(row)
                return _serialize(row)
        raise RuntimeError("Player feature segment could not be saved.")

    @staticmethod
    def materialize_offers(
        offers: list[dict],
        *,
        limit: int = 250,
        max_workers: int = 4,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict:
        unique: dict[str, dict] = {}
        for offer in offers:
            player = str(offer.get("player") or "").strip()
            sport = str(offer.get("sport") or offer.get("league") or "").upper()
            stat = str(offer.get("stat") or "").strip()
            if not player or not sport or not stat:
                continue
            unique.setdefault(PlayerFeatureRepository.feature_key(player, sport, stat), offer)
            if len(unique) >= max(1, limit):
                break
        built = 0
        failed = []
        total = len(unique)
        if not total:
            return {"requested": 0, "materialized": 0, "failed": []}

        def materialize_offer(offer: dict) -> dict:
            PlayerFeatureRepository.history(
                str(offer.get("player") or ""),
                str(offer.get("sport") or offer.get("league") or ""),
                str(offer.get("stat") or ""),
                team=str(offer.get("team") or ""),
                refresh=True,
            )
            return offer

        workers = max(1, min(int(max_workers), total, 8))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="edgeiq-features") as executor:
            futures = {executor.submit(materialize_offer, offer): offer for offer in unique.values()}
            for completed, future in enumerate(as_completed(futures), start=1):
                offer = futures[future]
                try:
                    future.result()
                    built += 1
                except Exception as exc:
                    _log.warning("Player feature materialization failed for %s %s: %s", offer.get("player"), offer.get("stat"), exc)
                    failed.append({
                        "player": offer.get("player"),
                        "stat": offer.get("stat"),
                        "error": "This player feature segment could not be refreshed.",
                    })
                if progress:
                    progress(completed, total)
        return {"requested": len(unique), "materialized": built, "failed": failed[:20]}

    @staticmethod
    def invalidate_segments(rows: list[dict]) -> int:
        """Expire cached segments touched by newly stored final stats."""
        PlayerFeatureRepository._ensure_schema()
        with SessionLocal() as session:
            updated = PlayerFeatureRepository.expire_segments(session, rows)
            session.commit()
            return updated

    @staticmethod
    def expire_segments(session, rows: list[dict]) -> int:
        """Expire segments inside an existing transaction."""
        keys = {
            PlayerFeatureRepository.feature_key(row.get("player"), row.get("sport"), row.get("stat"))
            for row in rows
            if row.get("player") and row.get("sport") and row.get("stat")
        }
        if not keys:
            return 0
        expired_at = datetime(1970, 1, 1, tzinfo=UTC)
        updated = (
            session.query(PlayerFeatureModel)
            .filter(PlayerFeatureModel.feature_key.in_(keys))
            .update({PlayerFeatureModel.materialized_at: expired_at}, synchronize_session=False)
        )
        return int(updated or 0)

    @staticmethod
    def status() -> dict:
        PlayerFeatureRepository._ensure_schema()
        with SessionLocal() as session:
            count = session.query(PlayerFeatureModel).count()
            latest = session.query(PlayerFeatureModel).order_by(PlayerFeatureModel.materialized_at.desc()).first()
            return {
                "segments": count,
                "last_materialized_at": latest.materialized_at.isoformat() if latest else "",
            }


def _serialize(row: PlayerFeatureModel) -> dict:
    return {
        "feature_key": row.feature_key,
        "player_identity_id": row.player_identity_id,
        "player": row.player,
        "team": row.team,
        "sport": row.sport,
        "stat": row.stat,
        "sample_size": row.sample_size,
        "history": _json(row.history_json, []),
        "summary": _json(row.summary_json, {}),
        "source_updated_at": row.source_updated_at,
        "materialized_at": row.materialized_at.replace(tzinfo=UTC).isoformat() if row.materialized_at.tzinfo is None else row.materialized_at.isoformat(),
    }


def _json(value: str, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default


def _is_fresh(value: str, max_age_hours: float) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed >= datetime.now(UTC) - timedelta(hours=max(0.0, max_age_hours))
    except (TypeError, ValueError):
        return False


def _history_summary(history: list[dict]) -> dict:
    played = [row for row in history if str(row.get("status") or "played").lower() == "played" and row.get("actual") is not None]
    values = [float(row["actual"]) for row in played]
    minutes = [float(row["minutes"]) for row in played if row.get("minutes") is not None]
    opportunities = [float(row["opportunities"]) for row in played if row.get("opportunities") is not None]
    return {
        "season_average": round(mean(values), 3) if values else None,
        "recent_5_average": round(mean(values[:5]), 3) if values else None,
        "recent_10_average": round(mean(values[:10]), 3) if values else None,
        "expected_minutes": round(mean(minutes[:10]), 3) if minutes else None,
        "expected_opportunities": round(mean(opportunities[:10]), 3) if opportunities else None,
        "sample_size": len(values),
        "teams": sorted({str(row.get("team") or "") for row in played if row.get("team")}),
        "opponents": sorted({str(row.get("game") or "") for row in played if row.get("game")}),
    }
