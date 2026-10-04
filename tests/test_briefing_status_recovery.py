import json

import pytest
from fastapi import BackgroundTasks, HTTPException

from repository.database import SessionLocal
from repository.repositories.settings_repository import SettingsRepository
from web.application import briefing_service
from web.routers.briefing import BriefingDependencies, start_daily_briefing_scan


def test_scan_status_survives_a_busy_settings_write(monkeypatch):
    monkeypatch.setattr(briefing_service, "_scan_fallback", {})
    scan = briefing_service.new_daily_scan("PrizePicks", "WNBA")

    def locked(_key, _value):
        raise RuntimeError("database is locked")

    saved = briefing_service.save_daily_scan_status(scan, locked, "daily_briefing_scan_status")
    status = briefing_service.daily_scan_status_payload(
        "PrizePicks", "WNBA", lambda _key, default="": default,
        lambda raw: json.loads(raw) if raw else {},
        "daily_briefing_scan_status", "daily_briefing_scan_log",
    )

    assert status["current"]["id"] == saved["id"]
    assert status["current"]["status"] == "scanning_props"


def test_scan_status_does_not_show_another_sports_progress(monkeypatch):
    monkeypatch.setattr(briefing_service, "_scan_fallback", {})
    wnba = briefing_service.new_daily_scan("PrizePicks", "WNBA")
    status = briefing_service.daily_scan_status_payload(
        "PrizePicks", "NFL",
        lambda key, default="": json.dumps(wnba) if key == "daily_briefing_scan_status" else default,
        lambda raw: json.loads(raw) if raw else {},
        "daily_briefing_scan_status", "daily_briefing_scan_log",
    )

    assert status["current"]["status"] == "not_run_today"
    assert status["current"]["sport"] == "NFL"


def test_new_scan_does_not_replace_a_different_active_scan():
    active = briefing_service.new_daily_scan("PrizePicks", "WNBA")
    dependencies = BriefingDependencies(
        briefing=lambda *_args: {},
        new_scan=lambda *_args: (_ for _ in ()).throw(AssertionError("should not create")),
        save_scan=lambda scan: scan,
        run_scan=lambda *_args: {},
        scan_status=lambda *_args: {"current": active},
    )

    with pytest.raises(HTTPException) as error:
        start_daily_briefing_scan(BackgroundTasks(), platform="PrizePicks", sport="NFL", deps=dependencies)

    assert error.value.status_code == 409


def test_scan_status_write_restores_sqlite_busy_timeout():
    SettingsRepository.set("daily_briefing_scan_status", "{}")
    with SessionLocal() as session:
        assert session.connection().exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
