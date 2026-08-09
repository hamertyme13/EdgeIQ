from datetime import datetime
from zoneinfo import ZoneInfo

from web.app import _elapsed_job_due, _scheduled_job_overdue
from web.application.provider_health_service import build_data_health_payload


def test_elapsed_scheduler_does_not_require_clock_alignment():
    now = datetime(2026, 8, 9, 12, 17, tzinfo=ZoneInfo("America/New_York"))
    assert _elapsed_job_due("2026-08-09T11:46:00-04:00", now, 30) is True
    assert _elapsed_job_due("2026-08-09T11:48:00-04:00", now, 30) is False


def test_daily_job_is_only_overdue_after_its_scheduled_time():
    early = datetime(2026, 8, 9, 7, 30, tzinfo=ZoneInfo("America/New_York"))
    late = datetime(2026, 8, 9, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    assert _scheduled_job_overdue("08:00", "", early) is False
    assert _scheduled_job_overdue("08:00", "", late) is True
    assert _scheduled_job_overdue("08:00", "2026-08-09T08:05", late) is False


def test_data_health_surfaces_scheduler_and_shadow_failures(monkeypatch):
    monkeypatch.setattr("web.application.provider_health_service.cache_metrics", lambda: {})
    payload = build_data_health_payload({}, {}, "settlement", operational_health={
        "scheduler": {"failures": [{"job": "line_snapshots", "message": "provider unavailable"}]},
        "shadow_evaluation": {"queued": 10, "settled": 0, "settlement_failures": 2},
        "shadow_settlement": {"ran_at": "2026-08-09T12:00:00+00:00"},
    })
    assert payload["operations"]["status"] == "degraded"
    assert len(payload["operations"]["warnings"]) == 3
