from __future__ import annotations

from repository.database import SessionLocal
from repository.models.final_player_stat_model import FinalPlayerStatModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_


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
                    .filter(FinalPlayerStatModel.stat == prop.get("stat", ""))
                )
                game = prop.get("game", "")
                if game:
                    game_token = str(game).strip()
                    query = query.filter(
                        or_(
                            FinalPlayerStatModel.game == game_token,
                            FinalPlayerStatModel.game.ilike(f"%{game_token}%"),
                        )
                    )
                row = query.order_by(FinalPlayerStatModel.game_date.desc(), FinalPlayerStatModel.id.desc()).first()
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
                    .filter(FinalPlayerStatModel.stat == stat)
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
                ]
        except SQLAlchemyError:
            return []


def _normalize_row(row: dict) -> dict | None:
    try:
        actual = float(row["actual"])
    except (KeyError, TypeError, ValueError):
        return None

    player = str(row.get("player", "")).strip()
    sport = str(row.get("sport", "")).strip().upper()
    stat = str(row.get("stat", "")).strip()
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
    return "played"
