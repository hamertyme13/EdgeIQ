"""Exploratory interval coverage from locked forecasts and earlier settled games."""

from __future__ import annotations

from collections import defaultdict
from datetime import date as calendar_date
from math import ceil, isfinite


def evaluate_chronological_interval(
    rows: list[dict], *, target_coverage: float = 0.8,
    minimum_calibration: int = 30, minimum_dates: int = 5,
    minimum_evaluation: int = 10, minimum_test_dates: int = 2,
    maximum_actual: float | None = None,
) -> dict:
    """Evaluate intervals without letting any result from the test date calibrate itself."""
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        if row.get("history_provenance_status") != "verified":
            continue
        date = str(row.get("game_date") or "")
        try:
            actual, projection = float(row["actual"]), float(row["projection"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        try:
            date = calendar_date.fromisoformat(date).isoformat()
        except ValueError:
            continue
        if (not all(isfinite(value) and value >= 0 for value in (actual, projection))
                or maximum_actual is not None and (actual > maximum_actual or projection > maximum_actual)):
            continue
        by_date[date].append((actual, projection))

    errors: list[float] = []
    prior_dates = 0
    evaluated = hits = 0
    widths: list[float] = []
    daily: list[dict] = []
    for date in sorted(by_date):
        games = by_date[date]
        if len(errors) >= minimum_calibration and prior_dates >= minimum_dates:
            ordered = sorted(errors)
            rank = min(len(ordered), ceil((len(ordered) + 1) * target_coverage))
            radius = ordered[rank - 1]
            date_hits = 0
            for actual, projection in games:
                lower, upper = max(0.0, projection - radius), projection + radius
                date_hits += lower <= actual <= upper
                widths.append(upper - lower)
            hits += date_hits
            evaluated += len(games)
            daily.append({
                "game_date": date, "calibration_samples": len(errors),
                "radius": round(radius, 2), "evaluated": len(games), "inside": date_hits,
            })
        errors.extend(abs(actual - projection) for actual, projection in games)
        prior_dates += 1

    enough_later_games = evaluated >= minimum_evaluation and len(daily) >= minimum_test_dates
    status = (
        "exploratory_chronological" if enough_later_games else
        "insufficient_later_games" if evaluated else "insufficient_pregame_evidence"
    )
    return {
        "status": status,
        "target_coverage_pct": round(target_coverage * 100, 1),
        "eligible_samples": len(errors), "game_dates": prior_dates,
        "minimum_calibration": minimum_calibration, "minimum_dates": minimum_dates,
        "minimum_evaluation": minimum_evaluation, "minimum_test_dates": minimum_test_dates,
        "evaluated": evaluated, "inside": hits,
        "evaluated_game_dates": len(daily),
        "coverage_pct": round(100 * hits / evaluated, 1) if enough_later_games else None,
        "average_width": round(sum(widths) / evaluated, 2) if enough_later_games else None,
        "daily": daily[-20:],
        "note": "Research-only coverage of intervals formed from earlier locked forecast errors. Not a calibrated next-game guarantee or a promotion decision.",
    }
