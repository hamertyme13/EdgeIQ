"""Lightweight thread-safe TTL cache used by web/app.py singleton helpers.

Each ``TTLCache`` stores a single value with an expiry timestamp.  Callers
hold their own ``RLock`` for reads/writes — this class is intentionally not
responsible for locking so the call-site semantics stay unchanged.

Usage::

    _MY_CACHE: TTLCache[dict] = TTLCache()

    with _MY_LOCK:
        if not _MY_CACHE.expired():
            return _MY_CACHE.value
        result = compute_something()
        _MY_CACHE.set(result, ttl=30.0)
        return result
"""
from __future__ import annotations

import time
from threading import RLock
from typing import Generic, TypeVar

_K = TypeVar("_K")
_T = TypeVar("_T")


class TTLCache(Generic[_T]):
    """Single-slot TTL cache — no ``global`` statement required."""

    __slots__ = ("_expires", "_value")

    def __init__(self) -> None:
        self._expires: float = 0.0
        self._value: _T | None = None

    def expired(self, *, now: float | None = None) -> bool:
        """Return ``True`` when the cached value is absent or has expired."""
        return (now if now is not None else time.monotonic()) >= self._expires

    @property
    def value(self) -> _T:
        """Return the stored value.  Raises ``ValueError`` if never set."""
        if self._value is None:
            raise ValueError("Cache has no value yet")
        return self._value

    def set(self, value: _T, *, ttl: float) -> None:
        """Store *value* and mark it valid for *ttl* seconds from now."""
        self._value = value
        self._expires = time.monotonic() + ttl

    def get_or_none(self) -> _T | None:
        """Return the stored value, or ``None`` when expired / unset."""
        return None if self.expired() else self._value

    def clear(self) -> None:
        """Discard the cached value immediately."""
        self._value = None
        self._expires = 0.0


class TTLMap(Generic[_K, _T]):
    """Thread-safe bounded TTL cache for multiple keys."""

    def __init__(self, *, max_size: int = 128) -> None:
        self._items: dict[_K, tuple[float, _T]] = {}
        self._max_size = max(1, int(max_size))
        self._lock = RLock()

    def get(self, key: _K, default: _T | None = None) -> _T | None:
        now = time.monotonic()
        with self._lock:
            cached = self._items.get(key)
            if cached is None:
                return default
            expires_at, value = cached
            if expires_at <= now:
                self._items.pop(key, None)
                return default
            return value

    def set(self, key: _K, value: _T, *, ttl: float) -> None:
        now = time.monotonic()
        with self._lock:
            self._items[key] = (now + max(0.0, float(ttl)), value)
            self._prune(now)

    def pop(self, key: _K) -> _T | None:
        with self._lock:
            cached = self._items.pop(key, None)
            return cached[1] if cached is not None else None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            self._prune(time.monotonic())
            return len(self._items)

    def _prune(self, now: float) -> None:
        for key in [key for key, (expires_at, _) in self._items.items() if expires_at <= now]:
            self._items.pop(key, None)
        overflow = len(self._items) - self._max_size
        if overflow > 0:
            for key, _ in sorted(self._items.items(), key=lambda item: item[1][0])[:overflow]:
                self._items.pop(key, None)
