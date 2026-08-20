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
    for row in history:
        row["minutes"] = 32

    over = forecast_prop("Player", "WNBA", "Points", 20.5, "Over", history=history)
    under = forecast_prop("Player", "WNBA", "Points", 20.5, "Under", history=history)

    assert over.source == "verified_history_distribution"
    assert over.projection > 20.5
    assert over.probability > 50
    assert round(over.probability + under.probability, 6) == 100
    assert over.paid_eligible is True
    assert over.distribution["median"] == 23.5
    assert over.distribution["percentile_25"] <= over.distribution["percentile_75"]
    assert over.distribution["floor"] <= over.distribution["ceiling"]
    assert round(
        over.distribution["probability_over_exact_line"]
        + over.distribution["probability_under_exact_line"],
        6,
    ) == 100


def test_forecast_routes_thin_history_to_market_prior_and_paper() -> None:
    result = forecast_prop("Player", "MLB", "Hits", 1.5, history=_history([1, 2, 1]))

    assert result.source == "market_prior"
    assert result.projection == 1.5
    assert result.probability == 50
    assert result.paid_eligible is False
    assert result.distribution["uncertainty_level"] == "High"
    assert result.distribution["median"] == 1


def test_forecast_exposes_minutes_and_opportunities_when_history_provides_them() -> None:
    history = _history([20, 21, 22, 23, 24] * 4)
    for index, row in enumerate(history):
        row["minutes"] = 30 + (index % 3)
        row["opportunities"] = 18 + (index % 2)

    result = forecast_prop("Player", "WNBA", "Points", 20.5, history=history)

    assert result.distribution["expected_minutes"] == 31
    assert result.distribution["expected_opportunities"] == 18.5


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
    assert result.model_version.endswith("v2.3.1")


def test_forecast_uses_small_opponent_sample_with_shrinkage() -> None:
    history = _history([18, 19, 20, 21, 18, 20, 19, 21, 18, 20] * 2)
    history[0].update({"game": "DAL@MIN", "team": "DAL", "actual": 29})
    history[1].update({"game": "MIN@DAL", "team": "DAL", "actual": 27})

    result = forecast_prop(
        "Paige Bueckers", "WNBA", "Points", 19.5, "Over",
        history=history, team="DAL", game="DAL@MIN",
    )

    assert result.features["opponent"] == "MIN"
    assert result.features["opponent_sample"] == 2
    assert result.features["opponent_mean"] > 27
    assert 0 < result.features["opponent_adjustment_weight"] < 0.30
    assert result.features["opponent_projection_delta"] > 0


def test_forecast_deduplicates_alias_rows_for_the_same_game() -> None:
    history = _history([18, 20, 22, 24, 26, 28])
    duplicate = {**history[0], "actual": 18, "stat": "Points+Rebounds+Assists"}

    result = forecast_prop(
        "Player", "WNBA", "Points + Rebounds + Assists", 22.5,
        history=[duplicate, *history],
    )

    assert result.sample_size == 6


def test_thin_high_uncertainty_forecast_shrinks_probability_toward_even() -> None:
    result = forecast_prop(
        "Player", "WNBA", "Points + Rebounds + Assists", 22.5, "Under",
        history=_history([0, 3, 7, 14, 17, 19, 33]),
    )

    assert result.features["evidence_strength"] < 0.35
    assert 45 <= result.probability <= 60
    assert result.paid_eligible is False
