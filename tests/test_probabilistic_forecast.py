from analytics.probabilistic_forecast import forecast_prop


def _history(values):
    return [
        {
            "actual": value,
            "status": "played",
            "game_date": f"2026-06-{30 - index:02d}",
            "game": f"A@B-{index}",
        }
        for index, value in enumerate(values)
    ]


def test_forecast_uses_verified_history_distribution_for_both_sides() -> None:
    history = _history([24, 23, 22, 25, 21, 24, 23, 22, 26, 24] * 2)

    over = forecast_prop("Player", "WNBA", "Points", 20.5, "Over", history=history)
    under = forecast_prop("Player", "WNBA", "Points", 20.5, "Under", history=history)

    assert over.source == "verified_history_distribution"
    assert over.projection > 20.5
    assert over.probability > 50
    assert round(over.probability + under.probability, 6) == 100
    assert over.paid_eligible is True


def test_forecast_routes_thin_history_to_market_prior_and_paper() -> None:
    result = forecast_prop("Player", "MLB", "Hits", 1.5, history=_history([1, 2, 1]))

    assert result.source == "market_prior"
    assert result.projection == 1.5
    assert result.probability == 50
    assert result.paid_eligible is False


def test_forecast_uses_robust_center_for_zero_inflated_stats() -> None:
    history = _history([0, 0, 0, 1, 0, 0, 2, 0, 0, 1] * 2)

    result = forecast_prop("Player", "MLB", "Home Runs", 0.5, history=history)

    assert result.features["projection_method"] == "zero_inflated_recent_median"
    assert result.features["zero_rate_recent_20"] >= 0.35
    assert result.projection == 0.25


def test_forecast_keeps_weighted_mean_for_continuous_distribution() -> None:
    result = forecast_prop(
        "Player",
        "WNBA",
        "Points",
        20.5,
        history=_history([18, 22, 24, 20, 25, 19, 23, 21, 24, 20] * 2),
    )

    assert result.features["projection_method"] == "recency_weighted_mean"
    assert result.features["walk_forward_validation"]["relative_improvement_pct"] == 4.8
    assert result.features["market_prior_weight"] == 0.5
    assert result.model_version.endswith("v2.2")
