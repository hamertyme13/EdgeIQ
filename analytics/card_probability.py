from __future__ import annotations

from analytics.correlation import estimate_correlation_matrix
from analytics.pickem_payouts import payout_analysis


def analyze_card_probability(
    props: list,
    platform: str,
    payout_type: str,
    *,
    displayed_multiplier: float | None = None,
    exact_schedule: dict | None = None,
) -> dict:
    probabilities = [_leg_probability(prop) for prop in props]
    matrix = estimate_correlation_matrix(props)
    payout = payout_analysis(
        probabilities,
        platform,
        payout_type,
        displayed_multiplier=displayed_multiplier,
        correlation_matrix=matrix,
        exact_schedule=exact_schedule,
    )
    pairs = []
    for left in range(len(props)):
        for right in range(left + 1, len(props)):
            correlation = matrix[left][right]
            if abs(correlation) < 0.04:
                continue
            pairs.append({
                "left": _leg_label(props[left]),
                "right": _leg_label(props[right]),
                "correlation": correlation,
                "risk": "shared outcome risk" if correlation > 0 else "cannibalization risk",
            })
    independent = payout.get("independent_all_hit_probability", 0.0)
    adjusted = payout.get("all_hit_probability", 0.0)
    return {
        **payout,
        "leg_probabilities": [round(value * 100.0, 2) for value in probabilities],
        "correlation_matrix": matrix,
        "correlated_pairs": pairs,
        "portfolio_dimensions": _dimensions(props),
        "correlation_probability_delta": round(float(adjusted) - float(independent), 2),
        "complete_card_probability": adjusted,
        "probability_method": "gaussian_copula_monte_carlo",
        "simulation_note": (
            "Complete-card probability uses deterministic Monte Carlo with conservative sport and game correlations. "
            "It is an estimate, not a guarantee."
        ),
    }


def _leg_probability(prop) -> float:
    snapshot = _value(prop, "forecast_snapshot") or {}
    distribution = snapshot.get("distribution") or {}
    direction = str(_value(prop, "direction") or "Over").lower()
    key = "probability_under_exact_line" if direction == "under" else "probability_over_exact_line"
    value = distribution.get(key)
    if value is None:
        value = _value(prop, "confidence")
    try:
        probability = float(value if value is not None else 50.0)
    except (TypeError, ValueError):
        probability = 50.0
    if probability > 1.0:
        probability /= 100.0
    return max(0.01, min(0.99, probability))


def _dimensions(props: list) -> dict:
    dimensions: dict[str, dict[str, int]] = {
        key: {} for key in ("players", "games", "teams", "stats", "directions")
    }
    for prop in props:
        for key, value in (
            ("players", _value(prop, "player")),
            ("games", _value(prop, "game")),
            ("teams", _value(prop, "team")),
            ("stats", _value(prop, "stat")),
            ("directions", _value(prop, "direction") or "Over"),
        ):
            label = str(value or "Unknown")
            dimensions[key][label] = dimensions[key].get(label, 0) + 1
    return dimensions


def _leg_label(prop) -> str:
    return f"{_value(prop, 'player')} {_value(prop, 'direction') or 'Over'} {_value(prop, 'stat')}"


def _value(prop, key: str):
    if isinstance(prop, dict):
        return prop.get(key)
    value = getattr(prop, key, None)
    if key == "player" and value is not None and not isinstance(value, str):
        return getattr(value, "name", "")
    if key == "team" and not value:
        return getattr(getattr(prop, "player", None), "team", "")
    return getattr(value, "value", value)
