from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from web.application import season_history_service as service
from web.application.season_history_service import season_window, start_season_history_sync


def test_season_window_uses_calendar_season_for_wnba_and_nfl() -> None:
    assert season_window("WNBA", date(2026, 8, 20)) == (date(2026, 5, 1), date(2026, 8, 20))
    assert season_window("NFL", date(2026, 8, 20)) == (date(2026, 7, 15), date(2026, 8, 20))
    assert season_window("NCAAF", date(2026, 8, 20)) == (date(2026, 7, 15), date(2026, 8, 20))


def test_season_window_crosses_year_for_nba() -> None:
    assert season_window("NBA", date(2026, 2, 2)) == (date(2025, 9, 15), date(2026, 2, 2))


def test_season_sync_rejects_unsupported_sport_in_plain_language() -> None:
    result = start_season_history_sync("TENNIS")
    assert result["accepted"] is False
    assert result["message"] == "Choose WNBA, NBA, NFL, college football, MLB, or NHL."


@pytest.mark.parametrize("checkpoint, expected", [
    ("", (date(2026, 9, 7), date(2026, 9, 13))),
    ("2026-09-12", (date(2026, 9, 10), date(2026, 9, 13))),
    ("2026-08-01", (date(2026, 7, 30), date(2026, 8, 12))),
])
def test_incremental_windows_are_bounded(monkeypatch, checkpoint, expected):
    monkeypatch.setattr(service.SettingsRepository, "get", lambda *args: checkpoint)
    assert service.sync_window("WNBA", today=date(2026, 9, 13)) == expected


def test_full_rescan_is_explicit(monkeypatch):
    monkeypatch.setattr(service.SettingsRepository, "get", lambda *args: "2026-09-12")
    assert service.sync_window("WNBA", today=date(2026, 9, 13), full_history=True) == (
        date(2026, 5, 1), date(2026, 9, 13))
    assert service.season_window("NBA", date(2026, 9, 1))[0] < date(2026, 9, 1)


def test_daily_job_calls_each_sport_once(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "sync_window", lambda sport: (date(2026, 9, 12), date(2026, 9, 13)))
    def run(sport, start, end, *, daily=False):
        assert daily
        calls.append(sport)
        return {"state": "complete"}
    monkeypatch.setattr(service, "_run_sync", run)
    service.run_daily_season_updates()
    assert sorted(calls) == sorted(service.SUPPORTED_SPORTS)


def test_failed_date_stops_and_preserves_retry_checkpoint(monkeypatch):
    saved = {}
    calls = []
    monkeypatch.setattr(service.SettingsRepository, "set", lambda key, value: saved.update({key: value}))
    def fetch(sport, day):
        calls.append(day)
        if day == date(2026, 9, 12):
            raise RuntimeError("provider unavailable")
        return []
    monkeypatch.setattr(service, "fetch_final_stats", fetch)
    service._run_sync_locked("WNBA", date(2026, 9, 11), date(2026, 9, 13))
    assert calls == [date(2026, 9, 11), date(2026, 9, 12)]
    assert saved["season_history:checkpoint:WNBA"] == "2026-09-11"
    assert service.season_history_status()["state"] == "paused"


@pytest.mark.parametrize("prefix", ["postgres://", "postgresql://"])
def test_railway_url_uses_installed_driver(prefix):
    from utils.database_url import normalize_database_url
    assert normalize_database_url(prefix + "user:secret@host/db?sslmode=require") == (
        "postgresql+psycopg://user:secret@host/db?sslmode=require")
    assert normalize_database_url("sqlite:///test.db") == "sqlite:///test.db"


def test_daily_success_is_not_replayed_but_manual_sync_still_runs(monkeypatch):
    saved = {}
    calls = []
    monkeypatch.setattr(service.SettingsRepository, "get", lambda key, default="": saved.get(key, default))
    monkeypatch.setattr(service.SettingsRepository, "set", lambda key, value: saved.update({key: value}))
    monkeypatch.setattr(service, "_sync_lock", lambda: nullcontext(True))
    def run(*args):
        calls.append(args)
        service._status.update(state="complete")
    monkeypatch.setattr(service, "_run_sync_locked", run)
    day = date(2026, 9, 15)
    service._run_sync("WNBA", day, day, daily=True)
    assert service._run_sync("WNBA", day, day, daily=True)["skipped"] is True
    service._run_sync("WNBA", day, day)
    assert len(calls) == 2


def test_busy_worker_does_not_overwrite_active_progress(monkeypatch):
    monkeypatch.setattr(service, "_sync_lock", lambda: nullcontext(False))
    monkeypatch.setattr(service, "_status", {"state": "running", "sport": "WNBA", "days_checked": 4})
    day = date(2026, 9, 15)
    assert service._run_sync("WNBA", day, day, daily=True)["state"] == "paused"
    assert service._status["state"] == "running"
    assert service._status["days_checked"] == 4


@pytest.mark.parametrize("acquired", [True, False])
def test_postgres_advisory_lock_release(monkeypatch, acquired):
    connection = MagicMock()
    connection.execute.return_value.scalar.return_value = acquired
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: nullcontext(connection))
    monkeypatch.setattr(service, "engine", engine)
    monkeypatch.setattr(service, "named_operation_lock", lambda name: nullcontext(True))
    with pytest.raises(RuntimeError), service._sync_lock() as locked:
        assert locked is acquired
        raise RuntimeError("worker interrupted")
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements[0] == "SELECT pg_try_advisory_lock(731904128)"
    assert ("SELECT pg_advisory_unlock(731904128)" in statements) is acquired
