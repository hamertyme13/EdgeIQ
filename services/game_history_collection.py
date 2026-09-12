from __future__ import annotations

import logging
from datetime import date, timedelta

from data.providers.espn import fetch_final_game_outcomes
from repository.repositories.settings_repository import SettingsRepository
from repository.repositories.team_history_repository import TeamHistoryRepository

_log = logging.getLogger(__name__)


def collect_team_history(sport: str, *, today: date | None = None) -> dict:
    """Refresh recent finals and backfill a bounded slice on each background scan."""
    today = today or date.today()
    if sport.upper() not in {"NBA", "WNBA"}:
        return {"stored": 0, "errors": []}
    key = f"game_team_history_cursor:{sport.upper()}"
    last_run = SettingsRepository.get(f"{key}:last_run")
    if last_run == today.isoformat():
        return {"stored": 0, "errors": [], "cached": True}
    try:
        cursor = date.fromisoformat(SettingsRepository.get(key))
    except ValueError:
        cursor = today - timedelta(days=3)
    cursor = min(cursor, today - timedelta(days=3))
    days = [today - timedelta(days=offset) for offset in (1, 2)]
    days += [cursor - timedelta(days=offset) for offset in range(5)]
    stored = 0
    errors = []
    for day in days:
        try:
            stored += TeamHistoryRepository.save_outcomes(fetch_final_game_outcomes(sport, day, include_team_stats=True))
        except Exception:
            _log.exception("Team history collection failed for %s %s", sport, day)
            errors.append(f"{sport} history for {day.isoformat()} could not be refreshed.")
    if not errors:
        next_cursor = cursor - timedelta(days=5)
        if next_cursor < today - timedelta(days=180):
            next_cursor = today - timedelta(days=3)
        SettingsRepository.set(key, next_cursor.isoformat())
        SettingsRepository.set(f"{key}:last_run", today.isoformat())
    return {"stored": stored, "errors": errors, "days_checked": len(days)}
