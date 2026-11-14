"""Wilson interval for an observed binary outcome rate, expressed in percent."""

from __future__ import annotations

from math import sqrt


def wilson_interval_95(wins: int, decisions: int) -> list[float] | None:
    if decisions <= 0 or not 0 <= wins <= decisions:
        return None
    z = 1.96
    p = wins / decisions
    denominator = 1 + z * z / decisions
    center = (p + z * z / (2 * decisions)) / denominator
    margin = z * sqrt(p * (1 - p) / decisions + z * z / (4 * decisions * decisions)) / denominator
    return [round(max(0.0, center - margin) * 100, 1), round(min(1.0, center + margin) * 100, 1)]
