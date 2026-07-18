from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher

from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.models.final_player_stat_model import FinalPlayerStatModel
from sqlalchemy.exc import SQLAlchemyError
from utils.stat_normalization import canonical_stat_label, stat_alias_labels


class FinalStatsRepository:

    @staticmethod
    def upsert_many(rows: list[dict]) -> int:
        saved = 0
        with SessionLocal() as session:
            for row in rows:
                normalized = _normalize_row(row)
                if normalized is None:
                    continue
                existing = (
                    session.query(FinalPlayerStatModel)
                    .filter_by(
                        player=normalized["player"],
                        sport=normalized["sport"],
                        stat=normalized["stat"],
                        game=normalized["game"],
                        game_date=normalized["game_date"],
                    )
                    .first()
                )
                if existing:
                    existing.actual = normalized["actual"]
                    existing.team = normalized["team"]
                    existing.status = normalized["status"]
                    existing.source = normalized["source"]
                else:
                    session.add(FinalPlayerStatModel(**normalized))
                saved += 1
            session.commit()
        return saved

    @staticmethod
    def find_actual(prop: dict) -> float | None:
        row = FinalStatsRepository.find_result(prop)
        if row is None or row.get("status") != "played":
            return None
        return row["actual"]

    @staticmethod
    def find_result(prop: dict) -> dict | None:
        try:
            with SessionLocal() as session:
                query = (
                    session.query(FinalPlayerStatModel)
                    .filter(FinalPlayerStatModel.player == prop.get("player", ""))
                    .filter(FinalPlayerStatModel.sport == prop.get("sport", ""))
                    .filter(FinalPlayerStatModel.stat.in_(stat_alias_labels(prop.get("stat", ""))))
                )
                game = prop.get("game", "")
                target_date = _prop_game_date(prop)
                placed_date = _prop_placed_date(prop)
                rows = query.order_by(FinalPlayerStatModel.game_date.desc(), FinalPlayerStatModel.id.desc()).limit(50).all()
                row = _best_matching_row(rows, game, prop.get("team", ""), target_date=target_date, placed_date=placed_date)
                if row is None:
                    row = _best_fuzzy_player_row(session, prop)
                if row is None:
                    return None
                return {
                    "actual": row.actual,
                    "status": row.status or "played",
                    "source": row.source,
                    "game": row.game,
                    "game_date": row.game_date,
                }
        except SQLAlchemyError:
            return None

    @staticmethod
    def history(player: str, stat: str, sport: str | None = None, limit: int = 100) -> list[dict]:
        try:
            with SessionLocal() as session:
                query = (
                    session.query(FinalPlayerStatModel)
                    .filter(FinalPlayerStatModel.player == player)
                    .filter(FinalPlayerStatModel.stat.in_(stat_alias_labels(stat)))
                )
                if sport:
                    query = query.filter(FinalPlayerStatModel.sport == sport)
                rows = (
                    query.order_by(FinalPlayerStatModel.game_date.desc(), FinalPlayerStatModel.id.desc())
                    .limit(limit)
                    .all()
                )
                return [
                    {
                        "player": row.player,
                        "team": row.team,
                        "sport": row.sport,
                        "stat": row.stat,
                        "game": row.game,
                        "game_date": row.game_date,
                        "actual": row.actual,
                        "status": row.status or "played",
                        "source": row.source,
                    }
                    for row in rows
                ] + _entry_prop_history(session, player, stat, sport, max(0, limit - len(rows)))
        except SQLAlchemyError:
            return []


def _normalize_row(row: dict) -> dict | None:
    try:
        actual = float(row["actual"])
    except (KeyError, TypeError, ValueError):
        return None

    player = str(row.get("player", "")).strip()
    sport = str(row.get("sport", "")).strip().upper()
    stat = canonical_stat_label(row.get("stat", ""))
    if not player or not sport or not stat:
        return None

    return {
        "player": player,
        "team": str(row.get("team", "")).strip(),
        "sport": sport,
        "stat": stat,
        "game": str(row.get("game", "")).strip(),
        "game_date": str(row.get("game_date", row.get("date", ""))).strip(),
        "actual": actual,
        "status": _normalize_status(row.get("status", "played")),
        "source": str(row.get("source", "import")).strip() or "import",
    }


def _normalize_status(value: object) -> str:
    status = str(value or "played").strip().lower()
    if status in {"dnp", "did_not_play", "did not play", "inactive"}:
        return "dnp"
    if status in {"live", "in_progress", "in-progress", "active"}:
        return "live"
    return "played"


def _best_matching_row(
    rows: list[FinalPlayerStatModel],
    game: object,
    team: object = "",
    target_date: str | None = None,
    placed_date: str | None = None,
) -> FinalPlayerStatModel | None:
    if not rows:
        return None
    if target_date:
        dated = [row for row in rows if str(row.game_date or "") == target_date]
        if dated:
            rows = dated
    requested_game = str(game or "").strip()
    if not requested_game:
        if placed_date:
            dated = [row for row in rows if str(row.game_date or "") >= placed_date]
            if dated:
                return dated[-1] if len(dated) == 1 else dated[0]
        return rows[0] if len(rows) == 1 else None

    requested_key = _game_key(requested_game)
    if not requested_key:
        return rows[0] if len(rows) == 1 else None

    for row in rows:
        if _game_key(row.game) == requested_key:
            return row

    team_key = _game_key(team)
    if team_key:
        for row in rows:
            row_key = _game_key(row.game)
            if requested_key in row_key and team_key in row_key:
                return row

    if len(requested_key) <= 4:
        for row in rows:
            if requested_key in _game_key(row.game):
                return row
    return rows[0] if len(rows) == 1 else None


def _best_fuzzy_player_row(session, prop: dict) -> FinalPlayerStatModel | None:
    player_key = _person_key(prop.get("player", ""))
    if not player_key:
        return None

    rows = (
        session.query(FinalPlayerStatModel)
        .filter(FinalPlayerStatModel.sport == prop.get("sport", ""))
        .filter(FinalPlayerStatModel.stat.in_(stat_alias_labels(prop.get("stat", ""))))
        .order_by(FinalPlayerStatModel.game_date.desc(), FinalPlayerStatModel.id.desc())
        .limit(250)
        .all()
    )
    if not rows:
        return None

    game = prop.get("game", "")
    team = prop.get("team", "")
    candidates = [row for row in rows if _player_name_matches(player_key, row.player)]
    if not candidates:
        return None

    return _best_matching_row(
        candidates,
        game,
        team,
        target_date=_prop_game_date(prop),
        placed_date=_prop_placed_date(prop),
    ) or (candidates[0] if len(candidates) == 1 else None)


def _prop_game_date(prop: dict) -> str | None:
    game_time = str(prop.get("game_time") or "").strip()
    if not game_time:
        return None
    try:
        return datetime.fromisoformat(game_time.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _prop_placed_date(prop: dict) -> str | None:
    placed = prop.get("_placed_date")
    if placed is None:
        return None
    if hasattr(placed, "isoformat"):
        return placed.isoformat()
    text = str(placed or "").strip()
    return text[:10] if text else None


def _player_name_matches(requested_key: str, provider_name: object) -> bool:
    provider_key = _person_key(provider_name)
    if not provider_key:
        return False
    if requested_key == provider_key:
        return True
    if _last_name(requested_key) != _last_name(provider_key):
        return False
    return SequenceMatcher(None, requested_key, provider_key).ratio() >= 0.9


def _person_key(value: object) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalpha())


def _last_name(person_key: str) -> str:
    return person_key[-8:]


def _game_key(value: object) -> str:
    text = str(value or "").upper()
    for raw, normalized in _TEAM_ALIASES.items():
        text = text.replace(raw, normalized)
    return "".join(character for character in text if character.isalnum())


_TEAM_ALIASES = {
    "NYL": "NY",
    "LVA": "LV",
    "LAS": "LA",
    "WAS": "WSH",
}


def _entry_prop_history(session, player: str, stat: str, sport: str | None, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    query = (
        session.query(EntryPropModel, EntryModel)
        .join(EntryModel, EntryModel.id == EntryPropModel.entry_id)
        .filter(EntryModel.status == "Settled")
        .filter(EntryPropModel.player_name == player)
        .filter(EntryPropModel.stat.in_(stat_alias_labels(stat)))
        .filter(EntryPropModel.actual.isnot(None))
        .filter(EntryPropModel.final_source != "")
        .filter(EntryPropModel.final_source != "projection_estimate")
    )
    if sport:
        query = query.filter(EntryPropModel.sport == sport)
    rows = (
        query.order_by(EntryModel.settled_at.desc(), EntryPropModel.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "player": prop.player_name,
            "team": prop.team,
            "sport": prop.sport,
            "stat": prop.stat,
            "game": prop.game,
            "game_date": entry.settled_at.date().isoformat() if entry.settled_at else "",
            "actual": prop.actual,
            "status": prop.final_status or "played",
            "source": prop.final_source or "edgeiq_entry",
            "entry_id": entry.id,
            "result": prop.final_result,
        }
        for prop, entry in rows
    ]
