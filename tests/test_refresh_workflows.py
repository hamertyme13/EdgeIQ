from datetime import UTC, datetime
from pathlib import Path

import web.app as web_app
from web.application.operations_service import sync_payload
from web.version import STATIC_ASSET_VERSION


def test_sync_refreshes_final_stats_before_settlement_without_duplicate_provider_work() -> None:
    calls: list[str] = []

    payload = sync_payload(
        False,
        classify_economics=lambda: {},
        import_final_stats_file=lambda: {},
        import_bet_history_file=lambda: {},
        auto_check=lambda _allow: calls.append("settle") or {"checked": 1},
        refresh_live_stats=lambda: calls.append("refresh") or {"imported": 1},
        dashboard=lambda: {},
    )

    assert calls == ["refresh", "settle"]
    assert payload["live_stats"]["imported"] == 1


def test_today_provider_refresh_is_separate_from_briefing_refresh() -> None:
    javascript = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "/api/automation/start-provider-refresh" in javascript
    refresh_function = javascript[javascript.index("async function refreshTodayProviders"):javascript.index("async function loadAdvantageCenter")]
    assert "/api/automation/start-daily-refresh" not in refresh_function
    assert "loadDailyBriefing()" not in refresh_function
    assert "final results" not in refresh_function.lower()


def test_launcher_version_matches_static_cache_version() -> None:
    service_worker = Path("web/static/sw.js").read_text(encoding="utf-8")
    index = Path("web/static/index.html").read_text(encoding="utf-8")

    assert STATIC_ASSET_VERSION in service_worker
    assert f"?v={STATIC_ASSET_VERSION}" in index


def test_desktop_launchers_read_version_without_importing_web_app() -> None:
    for path in (Path("scripts/launch_edgeiq.sh"), Path("scripts/run_edgeiq_desktop.sh")):
        launcher = path.read_text(encoding="utf-8")
        assert "from web.version import STATIC_ASSET_VERSION" in launcher
        assert "from web.app import STATIC_ASSET_VERSION" not in launcher


def test_startup_does_not_eagerly_scan_runtime_status() -> None:
    source = Path("web/app.py").read_text(encoding="utf-8")
    lifespan = source[source.index("async def lifespan"):source.index("async def _settlement_refresh_loop")]

    assert "_runtime_status_payload" not in lifespan


def test_sync_payload_records_refresh_result() -> None:
    payload = sync_payload(
        False,
        classify_economics=lambda: {},
        import_final_stats_file=lambda: {},
        import_bet_history_file=lambda: {},
        auto_check=lambda _allow: {},
        refresh_live_stats=lambda: {"at": datetime.now(UTC).isoformat()},
        dashboard=lambda: {},
    )
    assert payload["live_stats"]["at"]
