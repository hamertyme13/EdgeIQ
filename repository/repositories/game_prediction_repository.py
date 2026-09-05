from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from repository.database import SessionLocal
from repository.models.game_prediction_model import GamePredictionModel


class GamePredictionRepository:
    @staticmethod
    def save(snapshot: dict) -> dict:
        generated_at = _datetime(snapshot.get("generated_at")) or datetime.now(UTC)
        key = _prediction_key(snapshot, generated_at)
        with SessionLocal() as session:
            existing = session.query(GamePredictionModel).filter_by(prediction_key=key).one_or_none()
            if existing is not None:
                return _row(existing)
            row = GamePredictionModel(
                prediction_key=key,
                sport=str(snapshot.get("sport") or "").upper(),
                game_id=str(snapshot.get("game_id") or ""),
                game=str(snapshot.get("game") or ""),
                home_team=str(snapshot.get("home_team") or ""),
                away_team=str(snapshot.get("away_team") or ""),
                game_start=str(snapshot.get("game_start") or ""),
                model_version=str(snapshot.get("model_version") or ""),
                home_win_probability=float(snapshot.get("home_win_probability") or 0.5),
                away_win_probability=float(snapshot.get("away_win_probability") or 0.5),
                expected_margin=float(snapshot.get("expected_margin") or 0.0),
                expected_total=float(snapshot.get("expected_total") or 0.0),
                expected_home_points=float(snapshot.get("expected_home_points") or 0.0),
                expected_away_points=float(snapshot.get("expected_away_points") or 0.0),
                expected_pace=snapshot.get("expected_pace"),
                blowout_probability=snapshot.get("blowout_probability"),
                game_script=str(snapshot.get("game_script") or "neutral"),
                game_script_confidence=float(snapshot.get("game_script_confidence") or 0.0),
                data_quality=str(snapshot.get("data_quality") or "Thin"),
                evidence_json=json.dumps(snapshot.get("evidence") or {}, sort_keys=True, default=str),
                generated_at=generated_at,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.query(GamePredictionModel).filter_by(prediction_key=key).one()
                return _row(existing)
            session.refresh(row)
            return _row(row)

    @staticmethod
    def latest(*, sport: str = "", limit: int = 50) -> list[dict]:
        try:
            with SessionLocal() as session:
                query = session.query(GamePredictionModel)
                if sport:
                    query = query.filter(GamePredictionModel.sport == sport.upper())
                rows = query.order_by(GamePredictionModel.generated_at.desc()).limit(limit).all()
                return [_row(row) for row in rows]
        except SQLAlchemyError:
            return []

    @staticmethod
    def settle(game_id: str, actual_home_points: float, actual_away_points: float, source: str) -> int:
        with SessionLocal() as session:
            rows = session.query(GamePredictionModel).filter_by(game_id=str(game_id)).filter(GamePredictionModel.settled_at.is_(None)).all()
            for row in rows:
                row.actual_home_points = float(actual_home_points)
                row.actual_away_points = float(actual_away_points)
                row.actual_margin = float(actual_home_points) - float(actual_away_points)
                row.actual_total = float(actual_home_points) + float(actual_away_points)
                row.actual_home_win = 1.0 if actual_home_points > actual_away_points else 0.0
                row.outcome_source = source
                row.settled_at = datetime.now(UTC)
            session.commit()
            return len(rows)

    @staticmethod
    def latest_for_game(game_id: str) -> list[dict]:
        try:
            with SessionLocal() as session:
                rows = session.query(GamePredictionModel).filter_by(game_id=str(game_id)).order_by(GamePredictionModel.generated_at.desc()).all()
                latest_by_model: dict[str, dict] = {}
                for row in rows:
                    latest_by_model.setdefault(row.model_version, _row(row))
                return list(latest_by_model.values())
        except SQLAlchemyError:
            return []


def _prediction_key(snapshot: dict, generated_at: datetime) -> str:
    identity = "|".join((str(snapshot.get("sport") or "").upper(), str(snapshot.get("game_id") or snapshot.get("game") or ""), str(snapshot.get("model_version") or ""), generated_at.isoformat()))
    return hashlib.sha256(identity.encode()).hexdigest()[:40]


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _row(row: GamePredictionModel) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns} | {"evidence": json.loads(row.evidence_json or "{}")}
