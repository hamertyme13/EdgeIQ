"""Research-only NBA Points baseline from verified field-goal and free-throw attempts."""

from __future__ import annotations

from math import isfinite, sqrt
from statistics import mean, median

MODEL_VERSION = "nba-points-verified-shot-volume-shadow-v1"
VERIFIED_FINAL_SOURCES = ("espn", "nba_api", "balldontlie", "statshawk")


def shot_volume_challenger(games: list[dict]) -> dict:
    rows: list[tuple[float, float]] = []
    for row in games:
        if str(row.get("season_type") or "").lower() != "regular":
            continue
        if not str(row.get("source") or "").lower().startswith(VERIFIED_FINAL_SOURCES):
            continue
        try:
            points = float(row["actual"])
            field_goals = float(row["verified_field_goals_attempted"])
            free_throws = float(row["verified_free_throws_attempted"])
        except (KeyError, TypeError, ValueError):
            continue
        attempts = field_goals + free_throws
        if (all(isfinite(value) for value in (points, field_goals, free_throws))
                and 0 <= points <= 100 and 0 <= field_goals <= 60
                and 0 <= free_throws <= 60 and 0 < attempts <= 80):
            rows.append((points, attempts))

    result = {
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "status": "insufficient_verified_shot_volume",
        "sample_size": len(rows),
        "expected_points": None,
        "expected_attempts": None,
        "points_per_recorded_attempt": None,
        "probability": None,
        "validation": {"evaluated_games": 0, "challenger": None, "recent_points_average": None},
        "note": "Field-goal plus free-throw attempts are a simple volume proxy, not possessions. Research only; no calibrated probability or recommendation override.",
    }
    if len(rows) < 5:
        return result

    def predict(prior: list[tuple[float, float]]) -> float:
        recent = prior[-10:]
        return median(attempts for _, attempts in prior[-5:]) * sum(points for points, _ in recent) / sum(
            attempts for _, attempts in recent
        )

    chronological = list(reversed(rows))
    challenger_errors = []
    recent_errors = []
    for index in range(5, len(chronological)):
        prior = chronological[:index]
        estimate = predict(prior)
        if not 0 <= estimate <= 100:
            continue
        actual = chronological[index][0]
        challenger_errors.append(estimate - actual)
        recent_errors.append(mean(points for points, _ in prior[-5:]) - actual)

    def metrics(errors: list[float]) -> dict | None:
        if not errors:
            return None
        return {
            "mae": round(mean(abs(error) for error in errors), 2),
            "rmse": round(sqrt(mean(error * error for error in errors)), 2),
        }

    estimate = predict(chronological)
    if not 0 <= estimate <= 100:
        result["status"] = "implausible_shot_volume_estimate"
        return result
    recent = rows[:10]
    result.update({
        "status": "shadow_evaluation" if challenger_errors else "awaiting_holdout",
        "expected_points": round(estimate, 2),
        "expected_attempts": round(median(attempts for _, attempts in rows[:5]), 1),
        "points_per_recorded_attempt": round(sum(points for points, _ in recent) / sum(attempts for _, attempts in recent), 3),
        "validation": {
            "evaluated_games": len(challenger_errors),
            "challenger": metrics(challenger_errors),
            "recent_points_average": metrics(recent_errors),
        },
    })
    return result
