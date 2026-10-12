"""Capture a provider board once per fresh cache generation, not per reader."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable


def cache_generation(
    selected: list[str],
    sport_filter: str | None,
    cache: dict,
    *,
    canonical: Callable[[str], str],
    fetcher_token: Callable[[str], int],
    model_version: str,
    now: float | None = None,
) -> tuple | None:
    """Return None when any selected provider lacks a fresh in-memory board."""
    if not selected:
        return None
    now = time.monotonic() if now is None else now
    generations = []
    for name in selected:
        platform = canonical(name)
        key = f"{platform}:{fetcher_token(platform)}"
        if platform in {"Underdog", "Sleeper"} and sport_filter:
            key = f"{key}:{sport_filter}"
        cached = cache.get(key)
        if not cached or cached[0] <= now:
            return None
        generations.append((key, cached[0]))
    return (tuple(generations), sport_filter or "All Sports", model_version)


class FeedCaptureGate:
    def __init__(self, *, max_generations: int = 128) -> None:
        self._guard = threading.Lock()
        self._key_locks: dict[Hashable, threading.Lock] = {}
        self._captured: OrderedDict[Hashable, None] = OrderedDict()
        self._max_generations = max_generations
        self._durations_ms: deque[float] = deque(maxlen=50)
        self._fetch_durations_ms: deque[float] = deque(maxlen=50)
        self._captures = 0
        self._reuses = 0
        self._failures = 0

    def capture(self, generation: Hashable | None, save: Callable[[], object], *, fetch_ms: float = 0.0) -> bool:
        with self._guard:
            self._fetch_durations_ms.append(max(0.0, fetch_ms))
            if generation is not None and generation in self._captured:
                self._reuses += 1
                return False
            key_lock = self._key_locks.setdefault(generation, threading.Lock()) if generation is not None else None

        if key_lock is None:
            self._save(save, generation)
            return True
        with key_lock:
            with self._guard:
                if generation in self._captured:
                    self._reuses += 1
                    return False
            self._save(save, generation)
            return True

    def _save(self, save: Callable[[], object], generation: Hashable | None) -> None:
        started = time.perf_counter()
        try:
            save()
        except Exception:
            with self._guard:
                self._failures += 1
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        with self._guard:
            self._captures += 1
            self._durations_ms.append(elapsed_ms)
            if generation is not None:
                self._captured[generation] = None
                while len(self._captured) > self._max_generations:
                    oldest, _ = self._captured.popitem(last=False)
                    self._key_locks.pop(oldest, None)

    def snapshot(self) -> dict:
        with self._guard:
            captures, reuses, failures = self._captures, self._reuses, self._failures
            write_times = list(self._durations_ms)
            fetch_times = list(self._fetch_durations_ms)
        return {
            "captures": captures,
            "reuses": reuses,
            "failures": failures,
            "last_capture_ms": round(write_times[-1], 1) if write_times else None,
            "p95_capture_ms": _p95(write_times),
            "last_fetch_ms": round(fetch_times[-1], 1) if fetch_times else None,
            "p95_fetch_ms": _p95(fetch_times),
        }


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95 + 0.999) - 1))], 1)
