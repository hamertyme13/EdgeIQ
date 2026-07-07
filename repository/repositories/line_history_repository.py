from __future__ import annotations

from datetime import datetime

from repository.database import SessionLocal
from repository.models.prop_line_history_model import PropLineHistoryModel


class LineHistoryRepository:

    @staticmethod
    def record(player: str, stat: str, platform: str, line: float) -> None:
        """Save a line snapshot if it differs from the most recent stored value."""
        with SessionLocal() as session:
            last = (
                session.query(PropLineHistoryModel)
                .filter_by(player=player, stat=stat, platform=platform)
                .order_by(PropLineHistoryModel.recorded_at.desc())
                .first()
            )
            # Only write if value changed (avoids duplicate rows on each refresh)
            if last is None or last.line != line:
                session.add(PropLineHistoryModel(
                    player=player, stat=stat, platform=platform, line=line
                ))
                session.commit()

    @staticmethod
    def get_history(player: str, stat: str, platform: str) -> list[dict]:
        """Return recorded snapshots oldest-first as list of {line, recorded_at}."""
        with SessionLocal() as session:
            rows = (
                session.query(PropLineHistoryModel)
                .filter_by(player=player, stat=stat, platform=platform)
                .order_by(PropLineHistoryModel.recorded_at.asc())
                .all()
            )
            return [
                {"line": r.line, "recorded_at": r.recorded_at}
                for r in rows
            ]

    @staticmethod
    def latest_previous(player: str, stat: str, platform: str) -> float | None:
        """Return the second-most-recent line value, or None if fewer than 2 records."""
        with SessionLocal() as session:
            rows = (
                session.query(PropLineHistoryModel)
                .filter_by(player=player, stat=stat, platform=platform)
                .order_by(PropLineHistoryModel.recorded_at.desc())
                .limit(2)
                .all()
            )
            return rows[1].line if len(rows) >= 2 else None
