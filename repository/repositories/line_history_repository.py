from __future__ import annotations

from repository.database import SessionLocal
from repository.models.prop_line_history_model import PropLineHistoryModel
from utils.entity_normalization import canonical_person_key
from utils.entity_normalization import canonical_matchup_key


class LineHistoryRepository:

    @staticmethod
    def record(player: str, stat: str, platform: str, line: float) -> None:
        """Save a line snapshot if it differs from the most recent stored value."""
        with SessionLocal() as session:
            rows = (
                session.query(PropLineHistoryModel)
                .filter_by(stat=stat, platform=platform)
                .order_by(PropLineHistoryModel.recorded_at.desc())
                .limit(200)
                .all()
            )
            player_key = canonical_person_key(player)
            last = next((row for row in rows if canonical_person_key(row.player) == player_key), None)
            # Only write if value changed (avoids duplicate rows on each refresh)
            if last is None or last.line != line:
                session.add(PropLineHistoryModel(
                    player=player, stat=stat, platform=platform, line=line,
                    game="", game_time="", line_offer_type="standard",
                ))
                session.commit()

    @staticmethod
    def record_many(lines: list[dict]) -> int:
        """Save changed line snapshots in one transaction."""
        if not lines:
            return 0
        saved = 0
        with SessionLocal() as session:
            players = {str(row.get("player", "")).strip() for row in lines if row.get("player")}
            stats = {str(row.get("stat", "")).strip() for row in lines if row.get("stat")}
            platforms = {str(row.get("platform", "")).strip() for row in lines if row.get("platform")}
            recent_rows = (
                session.query(PropLineHistoryModel)
                .filter(
                    PropLineHistoryModel.player.in_(players),
                    PropLineHistoryModel.stat.in_(stats),
                    PropLineHistoryModel.platform.in_(platforms),
                )
                .order_by(PropLineHistoryModel.recorded_at.desc(), PropLineHistoryModel.id.desc())
                .all()
            )
            latest: dict[tuple[str, str, str, str, str], PropLineHistoryModel] = {}
            for item in recent_rows:
                key = (
                    canonical_person_key(item.player),
                    item.stat,
                    item.platform,
                    canonical_matchup_key(getattr(item, "game", "")),
                    str(getattr(item, "line_offer_type", "standard") or "standard").lower(),
                )
                latest.setdefault(key, item)
            for row in lines:
                player = str(row.get("player", "")).strip()
                stat = str(row.get("stat", "")).strip()
                platform = str(row.get("platform", "")).strip()
                line = row.get("line")
                game = str(row.get("game", "")).strip()
                game_time = str(row.get("game_time", "")).strip()
                offer_type = str(row.get("line_offer_type") or row.get("odds_type") or "standard").strip().lower()
                if not player or not stat or not platform or line is None:
                    continue
                player_key = canonical_person_key(player)
                game_key = canonical_matchup_key(game)
                key = (player_key, stat, platform, game_key, offer_type)
                last = latest.get(key)
                line_value = float(line)
                if last is None or last.line != line_value:
                    snapshot = PropLineHistoryModel(
                        player=player, stat=stat, platform=platform, line=line_value,
                        game=game, game_time=game_time, line_offer_type=offer_type,
                    )
                    session.add(snapshot)
                    latest[key] = snapshot
                    saved += 1
            if saved:
                session.commit()
        return saved

    @staticmethod
    def get_history(
        player: str,
        stat: str,
        platform: str,
        game: str | None = None,
        line_offer_type: str | None = None,
    ) -> list[dict]:
        """Return recorded snapshots oldest-first as list of {line, recorded_at}."""
        with SessionLocal() as session:
            base_query = session.query(PropLineHistoryModel).filter_by(stat=stat, platform=platform)
            candidates = (
                base_query
                .filter_by(player=player)
                .order_by(PropLineHistoryModel.recorded_at.asc())
                .all()
            )
            player_key = canonical_person_key(player)
            if candidates:
                rows = candidates
            else:
                candidates = base_query.order_by(PropLineHistoryModel.recorded_at.asc()).all()
                rows = [row for row in candidates if canonical_person_key(row.player) == player_key]
            if game:
                game_key = canonical_matchup_key(game)
                rows = [row for row in rows if canonical_matchup_key(getattr(row, "game", "")) == game_key]
            if line_offer_type:
                offer_key = str(line_offer_type).strip().lower()
                rows = [
                    row for row in rows
                    if str(getattr(row, "line_offer_type", "standard") or "standard").lower() == offer_key
                ]
            return [
                {
                    "line": r.line,
                    "recorded_at": r.recorded_at,
                    "game": getattr(r, "game", "") or "",
                    "game_time": getattr(r, "game_time", "") or "",
                    "line_offer_type": getattr(r, "line_offer_type", "standard") or "standard",
                }
                for r in rows
            ]

    @staticmethod
    def latest_previous(player: str, stat: str, platform: str) -> float | None:
        """Return the second-most-recent line value, or None if fewer than 2 records."""
        with SessionLocal() as session:
            candidates = (
                session.query(PropLineHistoryModel)
                .filter_by(stat=stat, platform=platform)
                .order_by(PropLineHistoryModel.recorded_at.desc())
                .limit(200)
                .all()
            )
            player_key = canonical_person_key(player)
            rows = [row for row in candidates if canonical_person_key(row.player) == player_key][:2]
            return rows[1].line if len(rows) >= 2 else None
