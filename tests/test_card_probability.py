from analytics.card_probability import analyze_card_probability


def test_card_probability_uses_exact_line_distribution_and_provider_payout():
    props = [
        {
            "player": "QB", "team": "AAA", "sport": "NFL", "stat": "Passing Yards",
            "direction": "Over", "game": "AAA @ BBB", "confidence": 51,
            "forecast_snapshot": {"distribution": {"probability_over_exact_line": 62}},
        },
        {
            "player": "WR", "team": "AAA", "sport": "NFL", "stat": "Receiving Yards",
            "direction": "Over", "game": "AAA @ BBB", "confidence": 52,
            "forecast_snapshot": {"distribution": {"probability_over_exact_line": 59}},
        },
    ]

    result = analyze_card_probability(
        props, "Underdog", "standard", exact_schedule={"2": 3.5},
    )

    assert result["leg_probabilities"] == [62.0, 59.0]
    assert result["source"] == "exact_offer_snapshot"
    assert result["probability_method"] == "gaussian_copula_monte_carlo"
    assert result["complete_card_probability"] == result["all_hit_probability"]
    assert result["correlated_pairs"][0]["correlation"] > 0
    assert result["portfolio_dimensions"]["games"] == {"AAA @ BBB": 2}


def test_card_probability_respects_under_distribution():
    result = analyze_card_probability([{
        "player": "A", "sport": "WNBA", "stat": "Points", "direction": "Under",
        "forecast_snapshot": {"distribution": {"probability_under_exact_line": 64.5}},
    }], "PrizePicks", "standard")

    assert result["leg_probabilities"] == [64.5]
