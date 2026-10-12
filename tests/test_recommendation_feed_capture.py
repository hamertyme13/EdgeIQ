import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from web.application.recommendation_feed_capture import FeedCaptureGate, cache_generation


def test_cache_generation_requires_fresh_exact_scope_and_model():
    now = 100.0
    cache = {
        "PrizePicks:7": (160.0, [{"player": "A"}]),
        "Underdog:8:WNBA": (165.0, [{"player": "B"}]),
    }
    kwargs = {
        "canonical": lambda name: name,
        "fetcher_token": lambda name: {"PrizePicks": 7, "Underdog": 8}[name],
        "model_version": "v1",
        "now": now,
    }
    generation = cache_generation(["PrizePicks", "Underdog"], "WNBA", cache, **kwargs)
    assert generation is not None
    assert generation != cache_generation(["PrizePicks", "Underdog"], "WNBA", cache, **{**kwargs, "model_version": "v2"})
    assert cache_generation(["PrizePicks", "Underdog"], "NBA", cache, **kwargs) is None
    assert cache_generation(["PrizePicks", "Underdog"], "WNBA", cache, **{**kwargs, "now": 166.0}) is None
    cache["Underdog:8:WNBA"] = (220.0, [])
    assert generation != cache_generation(["PrizePicks", "Underdog"], "WNBA", cache, **kwargs)


def test_capture_gate_deduplicates_concurrent_readers_and_retries_failure():
    gate = FeedCaptureGate()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def save():
        calls.append(1)
        started.set()
        assert release.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(gate.capture, ("PrizePicks", 1), save, fetch_ms=12)
        assert started.wait(timeout=2)
        second = pool.submit(gate.capture, ("PrizePicks", 1), save, fetch_ms=3)
        release.set()
        assert first.result(timeout=2) is True
        assert second.result(timeout=2) is False
    assert len(calls) == 1
    assert gate.snapshot()["reuses"] == 1
    assert gate.snapshot()["p95_capture_ms"] is not None

    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("database busy")

    with pytest.raises(RuntimeError):
        gate.capture(("PrizePicks", 2), flaky)
    assert gate.capture(("PrizePicks", 2), flaky) is True
    assert gate.snapshot()["failures"] == 1
    assert len(attempts) == 2


def test_fetch_props_saves_once_per_provider_cache_generation(monkeypatch):
    from web import app as web_app

    saved = []
    gate = FeedCaptureGate()
    cache = {"PrizePicks:7": (time.monotonic() + 60, [{"player": "A", "league": "WNBA"}])}
    monkeypatch.setattr(web_app, "_FEED_CAPTURE_GATE", gate)
    monkeypatch.setattr(web_app, "_PROP_FETCH_CACHE", cache)
    monkeypatch.setattr(web_app, "_selected_platforms", lambda _platform: ["PrizePicks"])
    monkeypatch.setattr(web_app, "_platform_fetcher_cache_token", lambda _platform: 7)
    monkeypatch.setattr(web_app, "_fetch_selected_platform_props", lambda _platform, _sport: [{"player": "A", "league": "WNBA", "trending_count": 1}])
    monkeypatch.setattr(web_app.ModelRehabilitationRepository, "save_feed", lambda payload: saved.append(payload))

    assert len(web_app._fetch_props("PrizePicks", "WNBA")) == 1
    assert len(web_app._fetch_props("PrizePicks", "WNBA")) == 1
    assert len(saved) == 1
    assert gate.snapshot()["reuses"] == 1
    cache["PrizePicks:7"] = (time.monotonic() + 120, cache["PrizePicks:7"][1])
    web_app._fetch_props("PrizePicks", "WNBA")
    assert len(saved) == 2
