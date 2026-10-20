from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import web.app as web_app
from web.app import _elapsed_job_due, _scheduled_job_overdue
from web.application.provider_health_service import build_data_health_payload


def test_elapsed_scheduler_does_not_require_clock_alignment():
    now = datetime(2026, 8, 9, 12, 17, tzinfo=ZoneInfo("America/New_York"))
    assert _elapsed_job_due("2026-08-09T11:46:00-04:00", now, 30) is True
    assert _elapsed_job_due("2026-08-09T11:48:00-04:00", now, 30) is False


def test_daily_job_detects_the_latest_missed_scheduled_occurrence():
    early = datetime(2026, 8, 9, 7, 30, tzinfo=ZoneInfo("America/New_York"))
    late = datetime(2026, 8, 9, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    assert _scheduled_job_overdue("08:00", "", early) is True
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


def test_data_health_exposes_plausibility_diagnostics(monkeypatch):
    monkeypatch.setattr("web.application.provider_health_service.cache_metrics", lambda: {})
    rejection = {"provider": "PrizePicks", "rejection_reason": "Line outside expected range."}

    payload = build_data_health_payload(
        {}, {}, "settlement", operational_health={"plausibility_rejections": [rejection]}
    )

    assert payload["operations"]["plausibility_rejections"] == [rejection]


def test_data_health_surfaces_due_complete_board_retries(monkeypatch):
    monkeypatch.setattr("web.application.provider_health_service.cache_metrics", lambda: {})
    complete_board = {
        "settlement_retry": {
            "due": 4,
            "deferred": 7,
            "message": "4 provider-board markets are ready for another verification attempt.",
        }
    }

    payload = build_data_health_payload(
        {}, {}, "settlement", operational_health={"complete_board": complete_board}
    )

    assert payload["operations"]["complete_board"] == complete_board
    assert payload["operations"]["status"] == "degraded"
    assert complete_board["settlement_retry"]["message"] in payload["operations"]["warnings"]


def test_runtime_status_returns_stale_snapshot_while_refreshing(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            started.append(True)

    web_app._RUNTIME_STATUS_CACHE.set({"overall": "stale-safe", "items": []}, ttl=0)
    monkeypatch.setattr(web_app.threading, "Thread", FakeThread)

    try:
        assert web_app._runtime_status_payload()["overall"] == "stale-safe"
        assert started == [True]
    finally:
        web_app._RUNTIME_STATUS_CACHE.clear()


def test_runtime_status_separates_model_inputs_from_provider_health(monkeypatch):
    monkeypatch.setattr(web_app, "_data_health_payload", lambda **_kwargs: {
        "summary": {"warnings": 0, "connected": 2, "total": 2}, "operations": {}
    })
    monkeypatch.setattr(web_app, "_model_health_payload", lambda: {"paid_entry_mode": "enabled", "trust_score": 80})
    monkeypatch.setattr(web_app, "build_ai_status_payload", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(web_app, "model_registry", lambda: {"router_version": "test"})
    monkeypatch.setattr(web_app.PlayerFeatureRepository, "status", lambda: {
        "segments": 20,
        "last_materialized_at": (datetime.now(UTC) - timedelta(hours=13)).isoformat(),
    })
    monkeypatch.setattr(web_app, "_deploy_readiness_payload", lambda: {})
    monkeypatch.setattr(web_app.SettingsRepository, "get", lambda *_args: "")
    monkeypatch.setattr(web_app.background_jobs, "list", lambda **_kwargs: [])

    payload = web_app._build_runtime_status_payload()
    items = {item["key"]: item for item in payload["items"]}

    assert items["providers"]["status"] == "ready"
    assert items["model"]["status"] == "ready"
    assert items["features"]["label"] == "Model Inputs"
    assert items["features"]["status"] == "attention"
    assert payload["overall"] == "attention"
