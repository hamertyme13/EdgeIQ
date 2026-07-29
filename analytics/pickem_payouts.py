from __future__ import annotations

import math
import random
from statistics import NormalDist


_PRIZEPICKS_STANDARD = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5}
_PRIZEPICKS_FLEX = {
    3: {3: 3.0, 2: 1.0},
    4: {4: 6.0, 3: 1.5},
    5: {5: 10.0, 4: 2.0, 3: 0.4},
    6: {6: 25.0, 5: 2.0, 4: 0.4},
}
_UNDERDOG_STANDARD = {2: 3.5, 3: 6.5, 4: 10.0, 5: 20.0, 6: 35.0, 7: 65.0, 8: 120.0}
_UNDERDOG_FLEX = {
    3: {3: 3.25, 2: 1.09},
    4: {4: 6.0, 3: 1.5},
    5: {5: 10.0, 4: 2.5},
    6: {6: 25.0, 5: 2.6, 4: 0.25},
    7: {7: 40.0, 6: 2.75, 5: 0.5},
    8: {8: 80.0, 7: 3.0, 6: 1.0},
}


def payout_schedule(platform: object, payout_type: object, leg_count: int) -> dict[int, float]:
    platform_key = str(platform or "PrizePicks").strip().lower()
    format_key = normalize_payout_type(payout_type)
    legs = int(leg_count or 0)
    if "underdog" in platform_key:
        if format_key == "flex":
            return dict(_UNDERDOG_FLEX.get(legs, {}))
        multiplier = _UNDERDOG_STANDARD.get(legs)
    else:
        if format_key == "flex":
            return dict(_PRIZEPICKS_FLEX.get(legs, {}))
        multiplier = _PRIZEPICKS_STANDARD.get(legs)
    return {legs: multiplier} if multiplier else {}


def payout_analysis(
    probabilities: list[float],
    platform: object,
    payout_type: object = "standard",
    displayed_multiplier: float | None = None,
    *,
    correlation_matrix: list[list[float]] | None = None,
    exact_schedule: dict[str, float] | dict[int, float] | None = None,
) -> dict:
    probs = [max(0.01, min(0.99, float(value))) for value in probabilities]
    schedule = (
        {int(wins): float(multiplier) for wins, multiplier in exact_schedule.items()}
        if exact_schedule
        else _scale_schedule(payout_schedule(platform, payout_type, len(probs)), displayed_multiplier)
    )
    independent_distribution = win_count_distribution(probs)
    distribution = (
        correlated_win_count_distribution(probs, correlation_matrix)
        if correlation_matrix and len(correlation_matrix) == len(probs)
        else independent_distribution
    )
    expected_return = sum(distribution.get(wins, 0.0) * multiplier for wins, multiplier in schedule.items())
    profit_probability = sum(
        distribution.get(wins, 0.0)
        for wins, multiplier in schedule.items()
        if multiplier > 1.0
    )
    refund_probability = sum(
        distribution.get(wins, 0.0)
        for wins, multiplier in schedule.items()
        if math.isclose(multiplier, 1.0, abs_tol=1e-9)
    )
    displayed_payout = max(schedule.values()) if schedule else 0.0
    return {
        "platform": _platform_label(platform),
        "payout_type": normalize_payout_type(payout_type),
        "leg_count": len(probs),
        "payouts": {str(wins): multiplier for wins, multiplier in sorted(schedule.items(), reverse=True)},
        "expected_return": round(expected_return, 4),
        "expected_value": round((expected_return - 1.0) * 100.0, 2),
        "profit_probability": round(profit_probability * 100.0, 2),
        "break_even_probability": round(100.0 / displayed_payout, 2) if displayed_payout > 0 else 0.0,
        "refund_probability": round(refund_probability * 100.0, 2),
        "all_hit_probability": round(distribution.get(len(probs), 0.0) * 100.0, 2),
        "independent_all_hit_probability": round(independent_distribution.get(len(probs), 0.0) * 100.0, 2),
        "correlation_adjusted": distribution is not independent_distribution,
        "displayed_multiplier": round(displayed_payout, 2),
        "source": "exact_offer_snapshot" if exact_schedule else "official_base_schedule",
        "requires_app_confirmation": not bool(exact_schedule),
        "message": "Confirm the final multiplier in the provider app because promotions, adjusted lines, and correlations can change it.",
    }


def settlement_return_multiplier(
    platform: object,
    payout_type: object,
    leg_results: list[dict],
    displayed_multiplier: float | None = None,
) -> float:
    active = [row for row in leg_results if str(row.get("result") or "") not in {"DNP", "Push"}]
    if len(active) < 2:
        return 1.0
    wins = sum(1 for row in active if row.get("result") == "Win")
    schedule = _scale_schedule(payout_schedule(platform, payout_type, len(active)), displayed_multiplier)
    return round(float(schedule.get(wins, 0.0)), 4)


def win_count_distribution(probabilities: list[float]) -> dict[int, float]:
    distribution = {0: 1.0}
    for probability in probabilities:
        next_distribution: dict[int, float] = {}
        for wins, chance in distribution.items():
            next_distribution[wins] = next_distribution.get(wins, 0.0) + chance * (1.0 - probability)
            next_distribution[wins + 1] = next_distribution.get(wins + 1, 0.0) + chance * probability
        distribution = next_distribution
    return distribution


def correlated_win_count_distribution(
    probabilities: list[float],
    correlation_matrix: list[list[float]],
    simulations: int = 8000,
) -> dict[int, float]:
    if not probabilities:
        return {0: 1.0}
    factor = _cholesky(correlation_matrix)
    if factor is None:
        return win_count_distribution(probabilities)
    thresholds = [NormalDist().inv_cdf(probability) for probability in probabilities]
    counts = {wins: 0 for wins in range(len(probabilities) + 1)}
    rng = random.Random(20260725)
    for _ in range(simulations):
        independent = [rng.gauss(0.0, 1.0) for _ in probabilities]
        correlated = [
            sum(factor[row][column] * independent[column] for column in range(row + 1))
            for row in range(len(probabilities))
        ]
        wins = sum(1 for value, threshold in zip(correlated, thresholds, strict=False) if value <= threshold)
        counts[wins] += 1
    return {wins: count / simulations for wins, count in counts.items()}


def _cholesky(matrix: list[list[float]]) -> list[list[float]] | None:
    size = len(matrix)
    result = [[0.0 for _ in range(size)] for _ in range(size)]
    try:
        for row in range(size):
            for column in range(row + 1):
                subtotal = sum(result[row][index] * result[column][index] for index in range(column))
                if row == column:
                    result[row][column] = math.sqrt(max(1e-8, float(matrix[row][row]) - subtotal))
                else:
                    result[row][column] = (float(matrix[row][column]) - subtotal) / result[column][column]
    except (IndexError, TypeError, ValueError, ZeroDivisionError):
        return None
    return result


def normalize_payout_type(value: object) -> str:
    return "flex" if str(value or "").strip().lower() in {"flex", "protected"} else "standard"


def _scale_schedule(schedule: dict[int, float], displayed_multiplier: float | None) -> dict[int, float]:
    if not schedule or displayed_multiplier in (None, 0, ""):
        return schedule
    top = max(schedule.values())
    target = float(displayed_multiplier)
    if top <= 0 or target <= 0:
        return schedule
    scale = target / top
    return {wins: round(multiplier * scale, 4) for wins, multiplier in schedule.items()}


def _platform_label(value: object) -> str:
    return "Underdog" if "underdog" in str(value or "").strip().lower() else "PrizePicks"
