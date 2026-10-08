"""Small, request-local timing recorder for briefing build stages."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


class BriefingTiming:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.stages_ms: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.stages_ms[name] = round(self.stages_ms.get(name, 0.0) + elapsed, 1)

    def snapshot(self) -> dict[str, float]:
        return {**self.stages_ms, "total_ms": round((time.perf_counter() - self.started) * 1000, 1)}
