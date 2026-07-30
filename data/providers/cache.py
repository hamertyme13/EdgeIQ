"""
Small HTTP cache for provider feeds.

Live prop APIs are useful but brittle. This helper gives callers a fresh response
when possible and a recent stale response when the network is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

_CACHE_DIR = Path(".edgeiq_cache") / "providers"
_LOCKS_GUARD = threading.Lock()
_CACHE_LOCKS: dict[str, threading.Lock] = {}
_METRICS_LOCK = threading.Lock()
_METRICS: dict[str, dict[str, int]] = {}


@dataclass(frozen=True)
class CachedResponse:
    data: Any
    stale: bool
    age_seconds: int
    etag: str = ""
    last_modified: str = ""


def get_json(
    url: str,
    *,
    cache_key: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    ttl_seconds: int = 300,
    retries: int = 2,
) -> CachedResponse:
    cache_path = _cache_path(cache_key or url)
    cached = _read_cache(cache_path)
    host = urlparse(url).netloc.lower() or "unknown"

    if cached and cached.age_seconds <= ttl_seconds:
        _record_metric(host, "cache_hits")
        return cached

    lock = _cache_lock(cache_path)
    with lock:
        cached = _read_cache(cache_path)
        if cached and cached.age_seconds <= ttl_seconds:
            _record_metric(host, "coalesced_hits")
            return cached

        request_headers = dict(headers or {})
        if cached and cached.etag:
            request_headers.setdefault("If-None-Match", cached.etag)
        if cached and cached.last_modified:
            request_headers.setdefault("If-Modified-Since", cached.last_modified)

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                _record_metric(host, "network_requests")
                response = requests.get(url, headers=request_headers or None, timeout=timeout)
                if response.status_code == 304 and cached:
                    _write_cache(
                        cache_path,
                        cached.data,
                        etag=cached.etag,
                        last_modified=cached.last_modified,
                    )
                    _record_metric(host, "not_modified")
                    return CachedResponse(
                        data=cached.data,
                        stale=False,
                        age_seconds=0,
                        etag=cached.etag,
                        last_modified=cached.last_modified,
                    )
                response.raise_for_status()
                data = response.json()
                etag = str(response.headers.get("ETag") or "")
                last_modified = str(response.headers.get("Last-Modified") or "")
                _write_cache(cache_path, data, etag=etag, last_modified=last_modified)
                _record_metric(host, "network_successes")
                return CachedResponse(
                    data=data,
                    stale=False,
                    age_seconds=0,
                    etag=etag,
                    last_modified=last_modified,
                )
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                _record_metric(host, "network_failures")
                if attempt < retries:
                    time.sleep(_retry_delay(attempt, getattr(exc, "response", None)))

        if cached:
            _record_metric(host, "stale_fallbacks")
            return CachedResponse(
                data=cached.data,
                stale=True,
                age_seconds=cached.age_seconds,
                etag=cached.etag,
                last_modified=cached.last_modified,
            )

        raise RuntimeError(f"Provider fetch failed and no cache is available: {last_error}")


def cache_status(url: str, *, ttl_seconds: int = 300) -> dict[str, Any]:
    cached = _read_cache(_cache_path(url))
    if cached is None:
        return {
            "cached": False,
            "age_seconds": None,
            "fresh": False,
            "ttl_seconds": ttl_seconds,
        }
    return {
        "cached": True,
        "age_seconds": cached.age_seconds,
        "fresh": cached.age_seconds <= ttl_seconds,
        "ttl_seconds": ttl_seconds,
    }


def cache_metrics() -> dict[str, Any]:
    with _METRICS_LOCK:
        hosts = {host: dict(values) for host, values in _METRICS.items()}
    totals: dict[str, int] = {}
    for values in hosts.values():
        for key, value in values.items():
            totals[key] = totals.get(key, 0) + int(value)
    avoided = totals.get("cache_hits", 0) + totals.get("coalesced_hits", 0) + totals.get("not_modified", 0)
    considered = avoided + totals.get("network_requests", 0)
    return {
        "totals": totals,
        "hosts": hosts,
        "requests_avoided": avoided,
        "avoidance_pct": round((avoided / considered) * 100.0, 1) if considered else 0.0,
    }


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{digest}.json"


def _read_cache(path: Path) -> CachedResponse | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        saved_at = float(payload["saved_at"])
        return CachedResponse(
            data=payload["data"],
            stale=False,
            age_seconds=max(0, int(time.time() - saved_at)),
            etag=str(payload.get("etag") or ""),
            last_modified=str(payload.get("last_modified") or ""),
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, data: Any, *, etag: str = "", last_modified: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": time.time(),
        "data": data,
        "etag": etag,
        "last_modified": last_modified,
    }
    temporary = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def _cache_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _LOCKS_GUARD:
        return _CACHE_LOCKS.setdefault(key, threading.Lock())


def _record_metric(host: str, metric: str) -> None:
    with _METRICS_LOCK:
        values = _METRICS.setdefault(host, {})
        values[metric] = values.get(metric, 0) + 1


def _retry_delay(attempt: int, response: requests.Response | None) -> float:
    retry_after = ""
    if response is not None:
        retry_after = str(response.headers.get("Retry-After") or "").strip()
    try:
        return max(0.0, min(10.0, float(retry_after)))
    except ValueError:
        base = min(2.0, 0.25 * (2 ** attempt))
        return base + random.uniform(0.0, base * 0.2)
