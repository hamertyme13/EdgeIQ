import threading
import time

import pytest

from web import app


def test_briefing_fetch_does_not_wait_for_active_provider_refresh(monkeypatch):
    cache = {}
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(app, "_PROP_FETCH_CACHE", cache)
    monkeypatch.setattr(app, "_PROP_FETCH_KEY_LOCKS", {})
    monkeypatch.setattr(app, "_platform_prop_fetcher", lambda _platform: lambda: [])
    monkeypatch.setattr(app, "_platform_fetcher_cache_token", lambda _platform: 1)
    monkeypatch.setattr(app, "_fetch_platform_props_uncached", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Concurrent request must not start another provider fetch")
    ))
    app._PROP_FETCH_KEY_LOCKS["Underdog:1"] = lock
    cache["Underdog:1"] = (time.monotonic() - 1, [{"player": "Expired"}])
    try:
        started = time.monotonic()
        assert app._fetch_platform_props("Underdog") == []
        assert time.monotonic() - started < 2
    finally:
        lock.release()


def test_selected_sport_refresh_passes_filter_to_provider(monkeypatch):
    calls = []

    def fetch(platform, *, force_refresh=False, sport_filter=None, progress=None):
        calls.append((platform, force_refresh, sport_filter, progress is not None))
        return [{"league": "WNBA"}, {"league": "NFL"}]

    class Context:
        def update(self, *_args):
            pass

    monkeypatch.setattr(app, "_fetch_platform_props", fetch)
    monkeypatch.setattr(app.SettingsRepository, "set", lambda *_args: None)
    monkeypatch.setattr(app.background_jobs, "submit", lambda _kind, run, **_kwargs: run(Context()))

    result = app._start_provider_refresh_job("Underdog", "WNBA")

    assert calls == [("Underdog", True, "WNBA", True)]
    assert result["offers"] == 1


def test_provider_refresh_reports_fetch_and_validation_stages(monkeypatch):
    phases = []
    monkeypatch.setattr(app, "_record_provider_fetch_status", lambda *_args, **_kwargs: None)

    assert app._fetch_platform_props_uncached(
        "Underdog", lambda: [], progress=lambda percent, phase: phases.append((percent, phase)),
    ) == []

    assert [percent for percent, _phase in phases] == [45, 70, 80]


def test_offer_eligibility_is_evaluated_once_per_provider_row(monkeypatch):
    checks = []
    offer = {"league": "WNBA", "player": "Test Player", "stat": "Points", "line": 12.5}
    monkeypatch.setattr(app, "_record_provider_fetch_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app, "_is_actionable_provider_prop", lambda _prop: True)

    def eligibility(prop):
        checks.append(prop)
        return {"eligible": True, "provider": "ESPN", "reasons": []}

    monkeypatch.setattr(app, "_end_to_end_prop_eligibility", eligibility)

    result = app._fetch_platform_props_uncached("Underdog", lambda: [offer])

    assert len(checks) == 1
    assert result[0]["end_to_end_confirmed"] is True
    assert result[0]["settlement_provider"] == "ESPN"


def test_forced_refresh_fails_when_provider_lock_does_not_clear(monkeypatch):
    class BusyLock:
        def acquire(self, **kwargs):
            assert kwargs == {"timeout": 30.0}
            return False

    monkeypatch.setattr(app, "_PROP_FETCH_CACHE", {})
    monkeypatch.setattr(app, "_PROP_FETCH_KEY_LOCKS", {"Underdog:1": BusyLock()})
    monkeypatch.setattr(app, "_platform_prop_fetcher", lambda _platform: lambda: [])
    monkeypatch.setattr(app, "_platform_fetcher_cache_token", lambda _platform: 1)

    with pytest.raises(TimeoutError, match="still refreshing offers"):
        app._fetch_platform_props("Underdog", force_refresh=True)
