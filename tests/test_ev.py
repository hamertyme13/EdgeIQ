from analytics.ev import expected_value


def test_expected_value_for_negative_odds():
    assert round(expected_value(-135, 0.64), 3) == 0.114
