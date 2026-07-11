"""
Small HTTP cache for provider feeds.

Live prop APIs are useful but brittle. This helper gives callers a fresh response
when possible and a recent stale response when the network is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


_CACHE_DIR = Path(".edgeiq_cache") / "providers"


@dataclass(frozen=True)
class CachedResponse:
    data: Any
    stale: bool
    age_seconds: int


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    ttl_seconds: int = 300,
    retries: int = 2,
) -> CachedResponse:
    cache_path = _cache_path(url)
    cached = _read_cache(cache_path)

    if cached and cached.age_seconds <= ttl_seconds:
        return cached

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            _write_cache(cache_path, data)
            return CachedResponse(data=data, stale=False, age_seconds=0)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.25 * (attempt + 1))

    if cached:
        return CachedResponse(
            data=cached.data,
            stale=True,
            age_seconds=cached.age_seconds,
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
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": time.time(),
        "data": data,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
