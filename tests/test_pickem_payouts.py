from analytics.pickem_payouts import payout_analysis, payout_schedule, settlement_return_multiplier


def test_draftkings_pick6_uses_user_entered_multiplier_without_claiming_official_schedule() -> None:
    result = payout_analysis([0.6, 0.6, 0.6], "DraftKings Pick6", displayed_multiplier=5.0)

    assert result["platform"] == "DraftKings Pick6"
    assert result["source"] == "user_entered_multiplier"
    assert result["payouts"] == {"3": 5.0}


def test_prizepicks_flex_expected_value_includes_partial_payouts():
    result = payout_analysis([0.6, 0.6, 0.6], "PrizePicks", "flex")

    assert result["payouts"] == {"3": 3.0, "2": 1.0}
    assert result["expected_return"] == 1.08
    assert result["expected_value"] == 8.0


def test_underdog_standard_uses_current_base_multiplier():
    assert payout_schedule("Underdog", "standard", 3) == {3: 6.5}


def test_displayed_multiplier_scales_adjusted_entry():
    result = payout_analysis([0.7, 0.7, 0.7], "PrizePicks", "standard", displayed_multiplier=9.0)

    assert result["displayed_multiplier"] == 9.0
    assert result["expected_return"] == 3.087
    assert result["break_even_probability"] == 11.11


def test_flex_settlement_uses_partial_win_multiplier():
    multiplier = settlement_return_multiplier(
        "Underdog",
        "flex",
        [{"result": "Win"}, {"result": "Win"}, {"result": "Loss"}],
    )

    assert multiplier == 1.09


def test_exact_offer_and_correlation_are_used_for_ev() -> None:
    independent = payout_analysis([0.6, 0.6], "PrizePicks", exact_schedule={"2": 3.0})
    correlated = payout_analysis(
        [0.6, 0.6],
        "PrizePicks",
        exact_schedule={"2": 3.0},
        correlation_matrix=[[1.0, 0.25], [0.25, 1.0]],
    )

    assert correlated["source"] == "exact_offer_snapshot"
    assert correlated["requires_app_confirmation"] is False
    assert correlated["correlation_adjusted"] is True
    assert correlated["all_hit_probability"] != independent["all_hit_probability"]
