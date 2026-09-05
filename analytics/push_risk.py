from __future__ import annotations

import math

from utils.stat_normalization import canonical_stat_label


def push_risk(prop: object) -> dict:
    line = _number(_value(prop, "line"))
    stat = canonical_stat_label(_value(prop, "stat"))
    snapshot = _value(prop, "forecast_snapshot") or {}
    features = snapshot.get("features") or {}
    distribution = snapshot.get("distribution") or {}
    mean = _number(distribution.get("expected_result"), _number(_value(prop, "projection"), line))
    sigma = max(0.0, _number(snapshot.get("standard_deviation"), 0.0) or 0.0)
    whole_number_line = line is not None and math.isclose(line, round(line), abs_tol=1e-9)
    tie_probability = _tie_probability(line, mean, sigma, stat) if whole_number_line else 0.0

    role_verified = bool(features.get("role_evidence_verified"))
    provider_identity = bool(_value(prop, "provider_player_id") or _value(prop, "player_identity_id"))
    availability_points = 0.0
    reasons: list[str] = []
    if whole_number_line:
        reasons.append("Whole-number line can tie exactly")
    if not role_verified:
        availability_points += 12.0
        reasons.append("Verified participation or workload evidence is limited")
    if not provider_identity:
        availability_points += 6.0
        reasons.append("Provider player identity is not locked")

    score = min(100.0, tie_probability + availability_points)
    return {
        "score": round(score, 1),
        "level": "High" if score >= 25 else "Medium" if score >= 12 else "Low",
        "whole_number_line": whole_number_line,
        "estimated_tie_probability": round(tie_probability, 1),
        "availability_risk": round(availability_points, 1),
        "reasons": reasons or ["Half-point line and verified participation reduce push exposure"],
    }


def _tie_probability(line: float | None, mean: float | None, sigma: float, stat: str) -> float:
    if line is None or mean is None or sigma <= 0 or not _is_discrete_stat(stat):
        return 0.0
    lower = _normal_cdf((line - 0.5 - mean) / sigma)
    upper = _normal_cdf((line + 0.5 - mean) / sigma)
    return max(0.0, min(35.0, (upper - lower) * 100.0))


def _is_discrete_stat(stat: str) -> bool:
    key = str(stat or "").lower()
    return not any(token in key for token in ("yards", "fantasy", "percentage", "fight time"))


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _value(prop: object, key: str):
    return prop.get(key) if isinstance(prop, dict) else getattr(prop, key, None)


def _number(value: object, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
