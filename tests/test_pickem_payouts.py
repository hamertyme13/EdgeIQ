from analytics.pickem_payouts import payout_analysis, payout_schedule, settlement_return_multiplier


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


def test_flex_settlement_uses_partial_win_multiplier():
    multiplier = settlement_return_multiplier(
        "Underdog",
        "flex",
        [{"result": "Win"}, {"result": "Win"}, {"result": "Loss"}],
    )

    assert multiplier == 1.09
