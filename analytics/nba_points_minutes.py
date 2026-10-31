"""Pregame, research-only NBA points baseline from verified scoring and minutes."""

from __future__ import annotations

from math import isfinite, sqrt
from statistics import mean, median

MODEL_VERSION = "nba-points-verified-minutes-shadow-v1"
VERIFIED_FINAL_SOURCES = ("espn", "nba_api", "balldontlie", "statshawk")


def minutes_challenger(games: list[dict]) -> dict:
    rows = []
    for row in games:
        if str(row.get("season_type") or "").lower() != "regular":
            continue
        if not str(row.get("source") or "").lower().startswith(VERIFIED_FINAL_SOURCES):
            continue
        try:
            points = float(row["actual"])
            minutes = float(row["verified_minutes"])
        except (KeyError, TypeError, ValueError):
            continue
        if isfinite(points) and 0 <= points <= 100 and isfinite(minutes) and 0 < minutes <= 65:
            rows.append((points, minutes))
    result = {
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "status": "insufficient_verified_minutes",
        "sample_size": len(rows),
        "expected_points": None,
        "expected_minutes": None,
        "points_per_minute": None,
        "probability": None,
        "validation": {"evaluated_games": 0, "challenger": None, "recent_points_average": None},
        "note": "Research-only minutes baseline; no calibrated probability or recommendation override.",
    }
    if len(rows) < 5:
        return result

    def predict(prior: list[tuple[float, float]]) -> float:
        recent = prior[-10:]
        return median(minutes for _, minutes in prior[-5:]) * sum(points for points, _ in recent) / sum(
            minutes for _, minutes in recent
        )

    chronological = list(reversed(rows))
    challenger_errors = []
    recent_errors = []
    for index in range(5, len(chronological)):
        prior = chronological[:index]
        actual = chronological[index][0]
        challenger_errors.append(predict(prior) - actual)
        recent_errors.append(mean(points for points, _ in prior[-5:]) - actual)

    def metrics(errors: list[float]) -> dict | None:
        if not errors:
            return None
        return {
            "mae": round(mean(abs(error) for error in errors), 2),
            "rmse": round(sqrt(mean(error * error for error in errors)), 2),
        }

    recent = rows[:10]
    result.update({
        "status": "shadow_evaluation" if challenger_errors else "awaiting_holdout",
        "expected_points": round(predict(chronological), 2),
        "expected_minutes": round(median(minutes for _, minutes in rows[:5]), 1),
        "points_per_minute": round(sum(points for points, _ in recent) / sum(minutes for _, minutes in recent), 3),
        "validation": {
            "evaluated_games": len(challenger_errors),
            "challenger": metrics(challenger_errors),
            "recent_points_average": metrics(recent_errors),
        },
    })
    return result
