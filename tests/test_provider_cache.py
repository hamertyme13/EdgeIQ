from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from data.providers import cache


class _Response:
    def __init__(self, data=None, *, status_code: int = 200, headers: dict | None = None):
        self._data = data
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._data


def _reset_cache_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cache, "_CACHE_DIR", tmp_path)
    cache._CACHE_LOCKS.clear()
    cache._METRICS.clear()


def test_get_json_reuses_fresh_response_and_reports_avoided_call(tmp_path, monkeypatch) -> None:
    _reset_cache_state(tmp_path, monkeypatch)
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(args[0])
        return _Response({"rows": [1]})

    monkeypatch.setattr(cache.requests, "get", fake_get)

    first = cache.get_json("https://api.example.com/props", ttl_seconds=60)
    second = cache.get_json("https://api.example.com/props", ttl_seconds=60)

    assert first.data == second.data == {"rows": [1]}
    assert calls == ["https://api.example.com/props"]
    assert cache.cache_metrics()["requests_avoided"] == 1


def test_get_json_coalesces_concurrent_cache_misses(tmp_path, monkeypatch) -> None:
    _reset_cache_state(tmp_path, monkeypatch)
    calls = []
    gate = threading.Barrier(3)

    def fake_get(*args, **kwargs):
        calls.append(args[0])
        time.sleep(0.05)
        return _Response({"ok": True})

    def worker(results: list) -> None:
        gate.wait()
        results.append(cache.get_json("https://api.example.com/board", ttl_seconds=60).data)

    monkeypatch.setattr(cache.requests, "get", fake_get)
    results: list[dict] = []
    threads = [threading.Thread(target=worker, args=(results,)) for _ in range(2)]
    for thread in threads:
        thread.start()
    gate.wait()
    for thread in threads:
        thread.join()

    assert results == [{"ok": True}, {"ok": True}]
    assert len(calls) == 1
    assert cache.cache_metrics()["totals"]["coalesced_hits"] == 1


def test_get_json_revalidates_stale_cache_with_etag(tmp_path, monkeypatch) -> None:
    _reset_cache_state(tmp_path, monkeypatch)
    url = "https://api.example.com/finals"
    path = cache._cache_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "saved_at": time.time() - 120,
        "data": {"final": True},
        "etag": '"abc"',
        "last_modified": "",
    }), encoding="utf-8")
    observed_headers = {}

    def fake_get(*args, **kwargs):
        observed_headers.update(kwargs.get("headers") or {})
        return _Response(status_code=304)

    monkeypatch.setattr(cache.requests, "get", fake_get)
    response = cache.get_json(url, ttl_seconds=60)

    assert response.data == {"final": True}
    assert response.stale is False
    assert observed_headers["If-None-Match"] == '"abc"'
    assert cache.cache_metrics()["totals"]["not_modified"] == 1
