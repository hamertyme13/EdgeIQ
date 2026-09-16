from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from threading import Lock, Thread
from zoneinfo import ZoneInfo

from sqlalchemy import text

from data.providers.espn import fetch_final_stats
from repository.database import engine
from repository.repositories.final_stats_repository import FinalStatsRepository
from repository.repositories.settings_repository import SettingsRepository
from services.operation_lock import named_operation_lock
from utils.time import utc_now

SUPPORTED_SPORTS = {"WNBA", "NBA", "NFL", "NCAAF", "MLB", "NHL"}
_log = logging.getLogger(__name__)
_lock = Lock()
_status: dict = {
    "state": "idle",
    "sport": "",
    "message": "Season history has not been synced in this app session.",
    "days_checked": 0,
    "days_total": 0,
    "rows_imported": 0,
    "records_inserted": 0,
    "records_updated": 0,
    "duplicates_removed": 0,
    "errors": [],
}


def start_season_history_sync(sport: str, full_history: bool = False) -> dict:
    sport_key = str(sport or "").upper()
    if sport_key not in SUPPORTED_SPORTS:
        return {**season_history_status(), "accepted": False, "message": "Choose WNBA, NBA, NFL, college football, MLB, or NHL."}
    with _lock:
        if _status["state"] in {"running", "queued"}:
            return {**_status, "accepted": False, "message": f"{_status['sport']} season history is already syncing."}
        start, end = sync_window(sport_key, full_history=full_history)
        _status.update({
            "state": "queued", "sport": sport_key,
            "message": f"Collecting completed {sport_key} games from {start:%B %-d} through {end:%B %-d}.",
            "started_at": utc_now().isoformat(), "completed_at": "",
            "days_checked": 0, "days_total": (end - start).days + 1,
            "rows_imported": 0, "records_inserted": 0, "records_updated": 0,
            "duplicates_removed": 0, "errors": [],
        })
    Thread(target=_run_sync, args=(sport_key, start, end), daemon=True, name=f"edgeiq-{sport_key.lower()}-season-sync").start()
    return {**season_history_status(), "accepted": True}


def season_history_status(sport: str = "") -> dict:
    if sport:
        try:
            saved = json.loads(SettingsRepository.get(f"season_history:status:{sport.upper()}", "{}"))
            if saved:
                return saved
        except (ValueError, TypeError):
            pass
    with _lock:
        return {**_status, "errors": list(_status.get("errors") or [])}


def season_window(sport: str, today: date | None = None) -> tuple[date, date]:
    current = today or datetime.now(ZoneInfo("America/New_York")).date()
    if sport in {"NBA", "NHL"}:
        start_year = current.year if (current.month, current.day) >= (9, 15) else current.year - 1
        return date(start_year, 9, 15), current
    starts = {"WNBA": (5, 1), "NFL": (7, 15), "NCAAF": (7, 15), "MLB": (3, 1)}
    month, day = starts[sport]
    year = current.year if (current.month, current.day) >= (month, day) else current.year - 1
    return date(year, month, day), current


def sync_window(sport: str, *, today: date | None = None, full_history: bool = False) -> tuple[date, date]:
    season_start, end = season_window(sport, today)
    if full_history:
        return season_start, end
    try:
        checkpoint = date.fromisoformat(SettingsRepository.get(f"season_history:checkpoint:{sport}", ""))
    except ValueError:
        checkpoint = end - timedelta(days=4)
    start = max(season_start, min(checkpoint - timedelta(days=2), end - timedelta(days=2)))
    return start, min(end, start + timedelta(days=13))


@contextmanager
def _sync_lock():
    with named_operation_lock("season-history") as acquired:
        if not acquired or engine.dialect.name != "postgresql":
            yield acquired
            return
        # Session advisory locks also coordinate distinct Railway replicas.
        with engine.connect() as connection:
            locked = bool(connection.execute(text("SELECT pg_try_advisory_lock(731904128)")).scalar())
            try:
                yield locked
            finally:
                if locked:
                    connection.execute(text("SELECT pg_advisory_unlock(731904128)"))


def run_daily_season_updates() -> dict:
    reports = {}
    for sport in sorted(SUPPORTED_SPORTS):
        start, end = sync_window(sport)
        reports[sport] = _run_sync(sport, start, end, daily=True)
    failures = [sport for sport, report in reports.items() if report.get("state") != "complete"]
    if failures:
        raise RuntimeError("Season history needs another attempt for: " + ", ".join(failures))
    return {"sports": reports, "message": "Incremental season history updated."}


def _run_sync(sport: str, start: date, end: date, *, daily: bool = False) -> dict:
    try:
        with _sync_lock() as acquired:
            if not acquired:
                result = {"state": "paused", "sport": sport, "message": "Another season update is running. Try again shortly."}
                with _lock:
                    if not daily and _status.get("state") == "queued" and _status.get("sport") == sport:
                        _status.update(result)
                return result
            today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
            daily_key = f"season_history:daily_success:{sport}"
            # Check inside the database lock so another replica cannot replay a
            # successful league when a different league requires a retry.
            if daily and SettingsRepository.get(daily_key, "") == today:
                return {"state": "complete", "sport": sport, "message": "Daily update already completed.", "skipped": True}
            with _lock:
                _status.update(state="running", sport=sport, days_checked=0, days_total=(end-start).days+1,
                               rows_imported=0, records_inserted=0, records_updated=0,
                               duplicates_removed=0, errors=[], started_at=utc_now().isoformat(), completed_at="")
            SettingsRepository.set(f"season_history:status:{sport}", json.dumps(season_history_status()))
            _run_sync_locked(sport, start, end)
            result = season_history_status()
            SettingsRepository.set(f"season_history:status:{sport}", json.dumps(result))
            if daily and result["state"] == "complete":
                SettingsRepository.set(daily_key, today)
            return result
    except Exception:
        _log.exception("Season history update failed for %s", sport)
        with _lock:
            _status.update(state="failed", sport=sport, message="Season history could not finish. Saved progress will be retried.")
    result = season_history_status()
    SettingsRepository.set(f"season_history:status:{sport}", json.dumps(result))
    return result


def _run_sync_locked(sport: str, start: date, end: date) -> None:
    cursor = start
    imported = 0
    inserted = 0
    updated = 0
    duplicates_removed = 0
    errors: list[str] = []
    consecutive_errors = 0
    while cursor <= end:
        try:
            rows = fetch_final_stats(sport, cursor)
            if rows:
                report = FinalStatsRepository.upsert_many_report(rows)
                imported += report["processed"]
                inserted += report["inserted"]
                updated += report["updated"]
                duplicates_removed += report["duplicates_removed"]
            consecutive_errors = 0
            SettingsRepository.set(f"season_history:checkpoint:{sport}", cursor.isoformat())
        except Exception:  # Provider failures are reported without exposing transport internals.
            _log.exception("Season history date failed for %s %s", sport, cursor)
            SettingsRepository.set(f"season_history:checkpoint:{sport}", (cursor - timedelta(days=1)).isoformat())
            consecutive_errors += 1
            errors.append(f"{cursor:%b %-d}: ESPN final box scores were temporarily unavailable.")
        with _lock:
            _status.update({
                "days_checked": (cursor - start).days + 1,
                "rows_imported": imported,
                "records_inserted": inserted,
                "records_updated": updated,
                "duplicates_removed": duplicates_removed,
                "errors": errors[-8:],
                "message": f"Checked {(cursor - start).days + 1} of {(end - start).days + 1} days: {inserted:,} new and {updated:,} updated player results.",
            })
        cursor += timedelta(days=1)
        SettingsRepository.set(f"season_history:status:{sport}", json.dumps(season_history_status()))
        if consecutive_errors:
            with _lock:
                _status.update({
                    "state": "paused",
                    "completed_at": utc_now().isoformat(),
                    "message": "Season sync paused at an unavailable date. Saved progress will be retried; no dates were skipped.",
                })
            return
    with _lock:
        _status["message"] = f"Finalizing {sport} history and checking for duplicate game records."
    # Per-row upserts handle repeated dates without scanning all historical rows.
    with _lock:
        _status.update({
            "state": "complete" if not errors else "complete_with_warnings",
            "completed_at": utc_now().isoformat(),
            "duplicates_removed": duplicates_removed,
            "message": (
                f"Season history sync finished: {inserted:,} new, {updated:,} updated, "
                f"and {duplicates_removed:,} duplicate records removed"
                + (f", with {len(errors)} provider warnings." if errors else ".")
            ),
        })
