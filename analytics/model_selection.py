from __future__ import annotations

from statistics import mean

from analytics.model_registry import RECENT_BASELINE_VERSION, SEASON_BASELINE_VERSION


def select_projection_champion(actuals: list[float], opportunity_projection: float) -> dict:
    """Choose a projection using only chronological, pre-outcome baseline evidence."""
    values = [float(value) for value in actuals]
    validation = _walk_forward_baselines(values)
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
    projection = season if champion["key"] == "season_average" else recent
    return {
        "projection": float(projection),
        "model_version": (
            SEASON_BASELINE_VERSION if champion["key"] == "season_average" else RECENT_BASELINE_VERSION
        ),
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
