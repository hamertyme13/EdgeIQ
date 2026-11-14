"""Validate and audit pregame historical stat ranges without treating them as forecasts."""

from __future__ import annotations

from math import isfinite


def locked_observed_range(snapshot: dict, *, minimum_samples: int = 5) -> tuple[float, float, float, float] | None:
    if snapshot.get("source") != "verified_history_distribution":
        return None
    try:
        samples = int(snapshot.get("sample_size") or 0)
    except (TypeError, ValueError):
        return None
    distribution = snapshot.get("distribution") or {}
    if samples < minimum_samples or not isinstance(distribution, dict):
        return None
    values: list[float] = []
    for key in ("floor", "percentile_25", "percentile_75", "ceiling"):
        try:
            value = float(distribution[key])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not isfinite(value) or value < 0:
            return None
        values.append(value)
    return (values[0], values[1], values[2], values[3]) if values == sorted(values) else None


def observed_range_audit(rows: list[dict]) -> dict:
    paired = []
    for row in rows:
        bounds = row.get("observed_range")
        try:
            actual = float(row["actual"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if bounds is not None and isfinite(actual) and actual >= 0:
            paired.append((bounds, actual))
    if not paired:
        return {"status": "unavailable", "samples": 0, "middle_half_coverage": None,
                "wider_range_coverage": None}
    middle = sum(bounds[1] <= actual <= bounds[2] for bounds, actual in paired)
    wider = sum(bounds[0] <= actual <= bounds[3] for bounds, actual in paired)
    return {
        "status": "descriptive_only", "samples": len(paired),
        "middle_half_hits": middle, "middle_half_coverage": round(100 * middle / len(paired), 1),
        "wider_range_hits": wider, "wider_range_coverage": round(100 * wider / len(paired), 1),
        "note": "Coverage of locked historical stat ranges, not a calibrated prediction interval.",
    }
