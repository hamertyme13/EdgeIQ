import json
from contextlib import contextmanager, suppress

import pytest
from pydantic import ValidationError

from web import app as web_app
from web.application.operations_service import update_refresh_schedule_payload
from web.application.schedule_service import retry_minutes
from web.schemas.settings import RefreshSchedulePayload


def test_briefing_schedule_update_preserves_other_jobs():
    saved = {}
    result = update_refresh_schedule_payload(
        RefreshSchedulePayload(daily_briefing="09:15"),
        current_schedule=lambda: {"morning_scan": "08:00", "auto_paper_samples": "08:30", "enabled": True},
        save_setting=lambda key, value: saved.update({key: value}),
        serialize=json.dumps,
    )
    assert result["schedule"] == {
        "morning_scan": "08:00", "auto_paper_samples": "08:30", "enabled": True,
        "daily_briefing": "09:15",
    }
    assert json.loads(saved["refresh_schedule"]) == result["schedule"]
    with pytest.raises(ValidationError):
        RefreshSchedulePayload(daily_briefing="25:99")


@pytest.mark.parametrize("scan_status,marked", [("ready", True), ("failed", False)])
def test_scheduled_briefing_uses_preferences_and_retries_failure(monkeypatch, scan_status, marked):
    settings = {}
    observed = []
    monkeypatch.setattr(web_app, "_refresh_schedule_payload", lambda: {
        "schedule": {"enabled": True, "daily_briefing": "00:00"},
    })
    monkeypatch.setattr(web_app, "_user_preferences", lambda: {
        "default_platform": "Underdog", "default_sport": "WNBA",
    })
    monkeypatch.setattr(web_app, "_run_daily_briefing_scan", lambda platform, sport, **kwargs: (
        observed.append((platform, sport, kwargs["trigger"])) or {"status": scan_status}
    ))
    monkeypatch.setattr(web_app, "_odds_provider_recovery_due", lambda now: False)
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: settings.update({key: value}))

    class Context:
        def update(self, *_args):
            pass

    def submit(_kind, callback, **_kwargs):
        with suppress(RuntimeError):
            callback(Context())
        return {"job_id": "scheduled-briefing", "reused": False}

    monkeypatch.setattr(web_app.background_jobs, "submit", submit)
    result = web_app._run_due_daily_operations_locked()

    assert result["jobs_run"] == ["daily_briefing"]
    assert observed == [("Underdog", "WNBA", "scheduled")]
    assert ("daily_scheduler_run:daily_briefing" in settings) is marked
    assert json.loads(settings["daily_scheduler_job_status:daily_briefing"])["state"] == (
        "completed" if marked else "failed"
    )
    second = web_app._run_due_daily_operations_locked()
    assert second["jobs_run"] == []
    assert observed == [("Underdog", "WNBA", "scheduled")]


def test_scheduled_briefing_does_not_overlap_another_process(monkeypatch):
    settings = {}
    observed = []

    @contextmanager
    def unavailable_lock(_name):
        yield False

    monkeypatch.setattr(web_app, "_refresh_schedule_payload", lambda: {
        "schedule": {"enabled": True, "daily_briefing": "00:00"},
    })
    monkeypatch.setattr(web_app, "_odds_provider_recovery_due", lambda _now: False)
    monkeypatch.setattr(web_app, "named_operation_lock", unavailable_lock)
    monkeypatch.setattr(web_app, "_run_scheduled_briefing", lambda: observed.append("ran"))
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: settings.update({key: value}))

    class Context:
        def update(self, *_args):
            pass

    def submit(_kind, callback, **_kwargs):
        with pytest.raises(RuntimeError, match="Another scheduled maintenance job"):
            callback(Context())
        return {"job_id": "overlap", "reused": False}

    monkeypatch.setattr(web_app.background_jobs, "submit", submit)
    web_app._run_due_daily_operations_locked()

    assert observed == []
    assert "daily_scheduler_run:daily_briefing" not in settings


def test_injury_refresh_does_not_repeat_full_provider_sync(monkeypatch):
    settings = {}
    refreshed = []
    monkeypatch.setattr(web_app, "_refresh_schedule_payload", lambda: {
        "schedule": {"enabled": True, "injury_refresh": "00:00"},
    })
    monkeypatch.setattr(web_app, "_odds_provider_recovery_due", lambda _now: False)
    monkeypatch.setattr(web_app, "_run_daily_refresh_now", lambda: (_ for _ in ()).throw(AssertionError("full sync")))
    monkeypatch.setattr(web_app, "fetch_injuries", lambda sport: refreshed.append(sport) or [])
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: settings.update({key: value}))

    class Context:
        def update(self, *_args):
            pass

    def submit(_kind, callback, **_kwargs):
        callback(Context())
        return {"job_id": "injury-refresh", "reused": False}

    monkeypatch.setattr(web_app.background_jobs, "submit", submit)
    result = web_app._run_due_daily_operations_locked()

    assert result["jobs_run"] == ["injury_refresh"]
    assert set(refreshed) == {"NBA", "WNBA", "NFL", "NCAAF", "NHL", "MLB"}


def test_morning_scan_builds_briefing_without_settlement_sync(monkeypatch):
    settings = {}
    calls = []
    monkeypatch.setattr(web_app, "_refresh_schedule_payload", lambda: {
        "schedule": {"enabled": True, "morning_scan": "00:00"},
    })
    monkeypatch.setattr(web_app, "_odds_provider_recovery_due", lambda _now: False)
    monkeypatch.setattr(web_app, "_run_daily_refresh_now", lambda: (_ for _ in ()).throw(AssertionError("full sync")))
    monkeypatch.setattr(web_app, "_run_scheduled_briefing", lambda: calls.append("briefing") or {"status": "ready"})
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(web_app.SettingsRepository, "set", lambda key, value: settings.update({key: value}))

    class Context:
        def update(self, *_args):
            pass

    def submit(_kind, callback, **_kwargs):
        callback(Context())
        return {"job_id": "morning-scan", "reused": False}

    monkeypatch.setattr(web_app.background_jobs, "submit", submit)
    result = web_app._run_due_daily_operations_locked()

    assert result["jobs_run"] == ["morning_scan"]
    assert calls == ["briefing"]


def test_heavy_maintenance_retries_less_often_than_result_checks():
    assert retry_minutes("daily_briefing") == 60
    assert retry_minutes("morning_scan") == 60
    assert retry_minutes("result_check") == 15
