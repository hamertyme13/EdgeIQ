from __future__ import annotations

from analytics.probabilistic_forecast import PropForecast, forecast_probability_at_line


def recommendation_sensitivity(
    forecast: PropForecast,
    *,
    line: float,
    direction: str,
    stat: str,
    threshold: float = 52.0,
) -> dict:
    """Show bounded model-only line sensitivity; provider availability is separate."""
    if forecast.source != "verified_history_distribution" or forecast.standard_deviation <= 0:
        return {"status": "unavailable", "reason": "Verified forecast history is insufficient for line sensitivity."}
    step = 0.5
    adverse_sign = 1 if direction.lower() == "over" else -1
    points = []
    for offset in (-2, -1, 0, 1, 2):
        shifted = round(line + adverse_sign * step * offset, 2)
        if shifted < 0:
            continue
        probability = forecast_probability_at_line(forecast, shifted, direction, stat)
        points.append({
            "line": shifted,
            "model_probability": probability,
            "qualifies_research_threshold": probability is not None and probability >= threshold,
            "offered": offset == 0,
        })
    current = next((point for point in points if point["offered"]), None)
    adverse = next((point for point in points if point["line"] == round(line + adverse_sign * step, 2)), None)
    return {
        "status": "model_only",
        "current_line": line,
        "direction": direction,
        "research_threshold": threshold,
        "line_step": step,
        "current_model_probability": current["model_probability"] if current else None,
        "adverse_half_point_probability": adverse["model_probability"] if adverse else None,
        "survives_adverse_half_point": bool(adverse and adverse["qualifies_research_threshold"]),
        "points": points,
        "note": "Hypothetical model sensitivity only. Shifted lines are not confirmed offers; calibration and payout must be rechecked.",
    }
