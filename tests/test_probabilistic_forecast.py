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

    assert 30 <= result.distribution["expected_minutes"] <= 32
    assert 18 <= result.distribution["expected_opportunities"] <= 19
    assert result.features["workload_evidence"]["verified"] is True
    assert result.features["opportunity_projection"]["verified"] is True
    assert result.features["opportunity_source"] == "verified_game_workload"
    assert result.distribution["production_per_opportunity"] is not None
    assert result.distribution["opportunity_evidence_games"] == 20


def test_opportunity_challenger_can_win_walk_forward_but_remains_paper_only() -> None:
    history = _history([value * 2 for value in range(20, 0, -1)])
    for value, row in zip(range(20, 0, -1), history, strict=True):
        row["opportunities"] = value
        row["minutes"] = 30

    result = forecast_prop("Player", "WNBA", "Points", 30.5, history=history)

    assert result.features["model_selection"]["method"] == "opportunity_aware"
    assert result.features["opportunity_walk_forward_validation"]["leakage_free"] is True
    assert result.paid_eligible is False
    assert "paper-only" in result.reason


def test_forecast_uses_robust_center_for_zero_inflated_stats() -> None:
    history = _history([0, 0, 0, 1, 0, 0, 2, 0, 0, 1] * 2)

    result = forecast_prop("Player", "MLB", "Home Runs", 0.5, history=history)

    assert result.features["projection_method"] == "zero_inflated_recent_median"
    assert result.features["zero_rate_recent_20"] >= 0.35
    assert result.projection == 0.4
    assert result.features["model_selection"]["method"] in {"season_average", "recent_10_average"}


def test_forecast_keeps_weighted_mean_for_continuous_distribution() -> None:
    result = forecast_prop(
        "Player",
        "WNBA",
        "Points",
        20.5,
        history=_history([18, 22, 24, 20, 25, 19, 23, 21, 24, 20] * 2),
    )

    assert result.features["projection_method"] == "recency_weighted_mean"
    validation = result.features["walk_forward_validation"]
    assert validation["selected_method"] in {"season_average", "recent_10_average"}
    assert all(row["samples"] == 15 for row in validation["baselines"])
    assert "chronologically" in validation["note"]
    assert result.features["market_prior_weight"] == 0.35
    assert result.model_version.endswith("baseline-v1")
    assert result.features["model_selection"]["challenger_projection"] is not None
    comparison = result.features["history_filter_comparison"]
    assert comparison["current_season"]["sample_size"] == 20
    assert comparison["trailing_history"]["probability"] is not None


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
    assert result.features["opponent_hit_rate"] == 100.0
    assert result.features["opponent_average_difference"] > 0


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


def test_forecast_requests_team_specific_history(monkeypatch) -> None:
    captured = {}

    def history(player, sport, stat, limit=100, team=""):
        captured.update({"player": player, "sport": sport, "team": team})
        rows = _history([1, 2, 1, 0, 1] * 4)
        for row in rows:
            row["team"] = team
        return rows

    monkeypatch.setattr("analytics.probabilistic_forecast.PlayerFeatureRepository.history", history)
    forecast_prop("Max Muncy", "MLB", "Hits", 0.5, team="LAD", game="LAD@COL")

    assert captured == {"player": "Max Muncy", "sport": "MLB", "team": "LAD"}


def test_forecast_applies_capped_verified_workload_adjustment() -> None:
    history = _history([20] * 20)
    for index, row in enumerate(history):
        row["minutes"] = 40 if index < 5 else 30

    result = forecast_prop("Player", "WNBA", "Rebounds", 9.5, history=history)

    workload = result.features["workload_evidence"]
    assert workload["verified"] is True
    assert workload["recent"] == 40
    assert workload["baseline"] == 30
    assert 0 < workload["adjustment_pct"] <= 15
    assert result.projection > 16.5
    assert result.distribution["workload_adjustment_pct"] == workload["adjustment_pct"]


def test_forecast_does_not_adjust_for_sparse_workload_data() -> None:
    history = _history([20] * 20)
    for row in history[:4]:
        row["minutes"] = 40

    result = forecast_prop("Player", "WNBA", "Rebounds", 19.5, history=history)

    workload = result.features["workload_evidence"]
    assert workload["verified"] is False
    assert workload["adjustment_pct"] == 0
