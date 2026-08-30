from __future__ import annotations

from datetime import date, timedelta
from threading import Lock, Thread

from data.providers.espn import fetch_final_stats
from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.time import utc_now

SUPPORTED_SPORTS = {"WNBA", "NBA", "NFL", "NCAAF", "MLB", "NHL"}
_lock = Lock()
_status: dict = {
    "state": "idle",
    "sport": "",
    "message": "Season history has not been synced in this app session.",
    "days_checked": 0,
    "days_total": 0,
    "rows_imported": 0,
    "errors": [],
}


def start_season_history_sync(sport: str) -> dict:
    sport_key = str(sport or "").upper()
    if sport_key not in SUPPORTED_SPORTS:
        return {**season_history_status(), "accepted": False, "message": "Choose WNBA, NBA, NFL, college football, MLB, or NHL."}
    with _lock:
        if _status["state"] == "running":
            return {**_status, "accepted": False, "message": f"{_status['sport']} season history is already syncing."}
        start, end = season_window(sport_key)
        _status.update({
            "state": "running", "sport": sport_key,
            "message": f"Collecting completed {sport_key} games from {start:%B %-d} through {end:%B %-d}.",
            "started_at": utc_now().isoformat(), "completed_at": "",
            "days_checked": 0, "days_total": (end - start).days + 1,
            "rows_imported": 0, "errors": [],
        })
    Thread(target=_run_sync, args=(sport_key, start, end), daemon=True, name=f"edgeiq-{sport_key.lower()}-season-sync").start()
    return {**season_history_status(), "accepted": True}


def season_history_status() -> dict:
    with _lock:
        return {**_status, "errors": list(_status.get("errors") or [])}


def season_window(sport: str, today: date | None = None) -> tuple[date, date]:
    current = today or date.today()
    if sport in {"NBA", "NHL"}:
        start_year = current.year if current.month >= 9 else current.year - 1
        return date(start_year, 9, 15), current
    starts = {"WNBA": (5, 1), "NFL": (7, 15), "NCAAF": (7, 15), "MLB": (3, 1)}
    month, day = starts[sport]
    return date(current.year, month, day), current


def _run_sync(sport: str, start: date, end: date) -> None:
    cursor = start
    imported = 0
    errors: list[str] = []
    consecutive_errors = 0
    while cursor <= end:
        try:
            rows = fetch_final_stats(sport, cursor)
            if rows:
                imported += FinalStatsRepository.upsert_many(rows)
            consecutive_errors = 0
        except Exception:  # Provider failures are reported without exposing transport internals.
            consecutive_errors += 1
            errors.append(f"{cursor:%b %-d}: ESPN final box scores were temporarily unavailable.")
        with _lock:
            _status.update({
                "days_checked": (cursor - start).days + 1,
                "rows_imported": imported,
                "errors": errors[-8:],
                "message": f"Checked {(cursor - start).days + 1} of {(end - start).days + 1} calendar days and saved {imported:,} player-stat results.",
            })
        cursor += timedelta(days=1)
        if consecutive_errors >= 5:
            with _lock:
                _status.update({
                    "state": "paused",
                    "completed_at": utc_now().isoformat(),
                    "message": "Season sync paused after five provider failures in a row. EdgeIQ kept all rows already saved; try again when ESPN is available.",
                })
            return
    with _lock:
        _status.update({
            "state": "complete" if not errors else "complete_with_warnings",
            "completed_at": utc_now().isoformat(),
            "message": f"Season history sync finished with {imported:,} verified player-stat results" + (f" and {len(errors)} provider warnings." if errors else "."),
        })
