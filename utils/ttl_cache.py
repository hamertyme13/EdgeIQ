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
from typing import Generic, TypeVar

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
