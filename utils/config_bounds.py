"""Read optional integer limits without letting malformed settings widen safety bounds."""

from __future__ import annotations

import os


def bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (AttributeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))
