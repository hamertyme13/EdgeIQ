from contextlib import contextmanager
from datetime import date, timedelta

from services import game_history_collection as collection


def test_nba_team_history_collects_bounded_days_once_per_day(monkeypatch):
    settings = {}
    days = []
    monkeypatch.setattr(collection.SettingsRepository, "get", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(collection.SettingsRepository, "set", lambda key, value: settings.update({key: value}))
    monkeypatch.setattr(collection, "fetch_final_game_outcomes", lambda sport, day, **kwargs: (
        days.append((sport, day, kwargs)) or [{"game_id": day.isoformat()}]
    ))
    monkeypatch.setattr(collection.TeamHistoryRepository, "save_outcomes", lambda rows: len(rows))

    today = date(2026, 10, 23)
    first = collection.collect_team_history("NBA", today=today)
    second = collection.collect_team_history("NBA", today=today)

    assert first == {"stored": 7, "errors": [], "days_checked": 7, "repair": True}
    assert second["cached"] is True
    assert settings["game_team_history_cursor:NBA:evidence_version"] == collection._NBA_EVIDENCE_VERSION
    assert len(days) == 7
    assert {day for _, day, _ in days} == {today - timedelta(days=offset) for offset in range(1, 8)}
    assert all(kwargs == {"include_team_stats": True} for _, _, kwargs in days)


def test_nba_team_history_repair_retries_without_advancing_backfill_cursor(monkeypatch):
    settings = {
        "game_team_history_cursor:NBA:last_run": "2026-10-23",
        "game_team_history_cursor:NBA": "2026-10-15",
    }
    calls = []
    monkeypatch.setattr(collection.SettingsRepository, "get", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(collection.SettingsRepository, "set", lambda key, value: settings.update({key: value}))

    def fetch(_sport, day, **_kwargs):
        calls.append(day)
        if day == date(2026, 10, 20):
            raise RuntimeError("provider unavailable")
        return []

    monkeypatch.setattr(collection, "fetch_final_game_outcomes", fetch)
    monkeypatch.setattr(collection.TeamHistoryRepository, "save_outcomes", lambda _rows: 0)

    result = collection.collect_team_history("NBA", today=date(2026, 10, 23))

    assert len(calls) == 7
    assert result["repair"] is True
    assert len(result["errors"]) == 1
    assert settings["game_team_history_cursor:NBA"] == "2026-10-15"
    assert "game_team_history_cursor:NBA:evidence_version" not in settings


def test_nba_team_history_resumes_backfill_after_repair(monkeypatch):
    settings = {
        "game_team_history_cursor:NBA:last_run": "2026-10-23",
        "game_team_history_cursor:NBA:evidence_version": collection._NBA_EVIDENCE_VERSION,
        "game_team_history_cursor:NBA": "2026-10-15",
    }
    days = []
    monkeypatch.setattr(collection.SettingsRepository, "get", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(collection.SettingsRepository, "set", lambda key, value: settings.update({key: value}))
    monkeypatch.setattr(collection, "fetch_final_game_outcomes", lambda _sport, day, **_kwargs: days.append(day) or [])
    monkeypatch.setattr(collection.TeamHistoryRepository, "save_outcomes", lambda _rows: 0)

    result = collection.collect_team_history("NBA", today=date(2026, 10, 24))

    assert result["repair"] is False
    assert len(days) == 7
    assert date(2026, 10, 23) in days
    assert date(2026, 10, 15) in days
    assert settings["game_team_history_cursor:NBA"] == "2026-10-10"


def test_nba_team_history_reports_provider_failure_for_scheduler(monkeypatch):
    monkeypatch.setattr(collection, "collect_team_history", lambda sport: {
        "stored": 0, "errors": [f"{sport} provider unavailable"], "days_checked": 1,
    })
    assert collection.collect_nba_team_history()["ok"] is False


def test_nba_team_history_busy_run_does_not_appear_successful(monkeypatch):
    @contextmanager
    def busy(_name):
        yield False

    monkeypatch.setattr(collection, "named_database_operation_lock", busy)

    result = collection.collect_nba_team_history()

    assert result["busy"] is True
    assert result["ok"] is False
