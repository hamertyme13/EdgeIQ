from __future__ import annotations

from statistics import mean

from analytics.model_registry import (
    OPPORTUNITY_CHALLENGER_VERSION,
    RECENT_BASELINE_VERSION,
    SEASON_BASELINE_VERSION,
)


def select_projection_champion(
    actuals: list[float],
    opportunity_projection: float,
    *,
    opportunity_validation: dict | None = None,
) -> dict:
    """Choose a projection using only chronological, pre-outcome baseline evidence."""
    values = [float(value) for value in actuals]
    validation = _walk_forward_baselines(values)
    if opportunity_validation and int(opportunity_validation.get("samples") or 0) >= 5:
        validation.append({
            "key": "opportunity_aware",
            "samples": int(opportunity_validation["samples"]),
            "mae": float(opportunity_validation["mae"]),
        })
    candidates = [row for row in validation if row["samples"] >= 5]
    champion = min(candidates, key=lambda row: row["mae"], default=None)
    if champion is None:
        return {
            "projection": float(opportunity_projection),
            "model_version": SEASON_BASELINE_VERSION,
            "method": "insufficient_walk_forward_history",
            "validation": validation,
            "challenger_projection": float(opportunity_projection),
        }
    season = mean(values)
    recent = mean(values[: min(10, len(values))])
    projections = {
        "season_average": season,
        "recent_10_average": recent,
        "opportunity_aware": float(opportunity_projection),
    }
    versions = {
        "season_average": SEASON_BASELINE_VERSION,
        "recent_10_average": RECENT_BASELINE_VERSION,
        "opportunity_aware": OPPORTUNITY_CHALLENGER_VERSION,
    }
    projection = projections[champion["key"]]
    return {
        "projection": float(projection),
        "model_version": versions[champion["key"]],
        "method": champion["key"],
        "validation": validation,
        "challenger_projection": float(opportunity_projection),
        "challenger_delta": round(float(opportunity_projection) - float(projection), 3),
    }


def _walk_forward_baselines(actuals_descending: list[float]) -> list[dict]:
    chronological = list(reversed(actuals_descending))
    errors: dict[str, list[float]] = {"season_average": [], "recent_10_average": []}
    for index in range(5, len(chronological)):
        train = chronological[:index]
        actual = chronological[index]
        errors["season_average"].append(abs(mean(train) - actual))
        errors["recent_10_average"].append(abs(mean(train[-10:]) - actual))
    return [
        {
            "key": key,
            "samples": len(values),
            "mae": round(mean(values), 4) if values else None,
        }
        for key, values in errors.items()
    ]
