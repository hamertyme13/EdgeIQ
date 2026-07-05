from services.betting import implied_probability

def test_positive_odds():
    assert round(implied_probability(150), 3) == 0.400

def test_negative_odds():
    assert round(implied_probability(-110), 3) == 0.524