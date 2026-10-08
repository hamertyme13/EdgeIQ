from analytics.probabilistic_forecast import forecast_probability_at_line, forecast_prop
from analytics.recommendation_sensitivity import recommendation_sensitivity


def _forecast():
    history = [
        {"actual": 20 + index % 7, "status": "played", "game_date": f"2026-07-{1 + index:02d}"}
        for index in range(20)
    ]
    return forecast_prop("Example Player", "WNBA", "Points", 22.5, history=history)


def test_exact_line_probability_changes_without_refitting_forecast():
    forecast = _forecast()
    standard = forecast_probability_at_line(forecast, 22.5, "Over", "Points")
    premium = forecast_probability_at_line(forecast, 24.5, "Over", "Points")
    discounted = forecast_probability_at_line(forecast, 20.5, "Over", "Points")

    assert standard is not None and abs(standard - forecast.probability) < 0.2
    assert premium is not None and discounted is not None
    assert premium < standard < discounted


def test_adverse_line_move_reduces_probability_for_both_directions():
    forecast = _forecast()
    over = recommendation_sensitivity(forecast, line=22.5, direction="Over", stat="Points")
    under = recommendation_sensitivity(forecast, line=22.5, direction="Under", stat="Points")

    assert over["status"] == under["status"] == "model_only"
    assert over["adverse_half_point_probability"] < over["current_model_probability"]
    assert under["adverse_half_point_probability"] < under["current_model_probability"]
    assert sum(point["offered"] for point in over["points"]) == 1
    assert all(0 <= point["model_probability"] <= 100 for point in over["points"])
    assert over["last_tested_qualifying_line"] is None or over["last_tested_qualifying_line"] >= 22.5
    assert under["last_tested_qualifying_line"] is None or under["last_tested_qualifying_line"] <= 22.5
    assert over["tested_adverse_range_end"] == 23.5
    assert under["tested_adverse_range_end"] == 21.5


def test_sensitivity_reports_first_failing_tested_line_without_extrapolation():
    forecast = _forecast()
    result = recommendation_sensitivity(forecast, line=22.5, direction="Over", stat="Points", threshold=99)
    assert result["last_tested_qualifying_line"] is None
    assert result["first_tested_failing_line"] == 22.5


def test_thin_history_does_not_invent_line_sensitivity():
    forecast = forecast_prop("Example Player", "WNBA", "Points", 22.5, history=[])

    assert forecast_probability_at_line(forecast, 23.5, "Over", "Points") is None
    assert recommendation_sensitivity(forecast, line=22.5, direction="Over", stat="Points")["status"] == "unavailable"


def test_discrete_whole_line_keeps_push_probability_out_of_both_sides():
    forecast = _forecast()
    over = forecast_probability_at_line(forecast, 22.0, "Over", "Points")
    under = forecast_probability_at_line(forecast, 22.0, "Under", "Points")

    assert over is not None and under is not None
    assert over + under < 100.0
