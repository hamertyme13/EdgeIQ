from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from analytics.kelly import half_kelly, kelly_fraction, suggested_wager
from analytics.pickem_payouts import payout_analysis, win_count_distribution
from analytics.probabilistic_forecast import forecast_prop
from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.stat_normalization import canonical_stat_label


@st.composite
def histories(draw):
    values = draw(st.lists(st.floats(min_value=0, max_value=100, allow_nan=False), min_size=5, max_size=60))
    return [
        {
            "actual": value,
            "status": "played",
            "game_date": f"2026-{1 + index // 27:02d}-{1 + index % 27:02d}",
            "game": "AAA@BBB",
            "team": "AAA",
        }
        for index, value in enumerate(values)
    ]


@given(histories(), st.floats(min_value=0.5, max_value=99.5, allow_nan=False), st.sampled_from(["Over", "Under"]))
@settings(max_examples=60, deadline=None)
def test_forecast_probability_and_interval_invariants(history, line, direction):
    result = forecast_prop(
        "Player", "WNBA", "Points", line, direction,
        history=history, team="AAA", game="AAA@BBB",
    )

    assert 0 <= result.probability <= 100
    distribution = result.distribution
    assert distribution["floor"] <= distribution["median"] <= distribution["ceiling"]
    assert math.isclose(
        distribution["probability_over_exact_line"] + distribution["probability_under_exact_line"],
        100.0,
        abs_tol=0.02,
    )


@given(
    st.integers(min_value=-5000, max_value=5000).filter(lambda value: value != 0),
    st.floats(min_value=0, max_value=1, allow_nan=False),
    st.floats(min_value=0, max_value=1_000_000, allow_nan=False),
)
def test_kelly_sizing_never_exceeds_bankroll(odds, probability, bankroll):
    assert 0 <= kelly_fraction(odds, probability) <= 1
    assert 0 <= half_kelly(odds, probability) <= 0.5
    assert 0 <= suggested_wager(odds, probability, bankroll) <= round(bankroll, 2)


@given(st.lists(st.floats(min_value=0, max_value=1, allow_nan=False), min_size=1, max_size=8))
def test_payout_distributions_are_complete(probabilities):
    distribution = win_count_distribution(probabilities)
    assert set(distribution) == set(range(len(probabilities) + 1))
    assert math.isclose(sum(distribution.values()), 1.0, abs_tol=1e-10)
    analysis = payout_analysis(probabilities, "Underdog", "flex")
    assert 0 <= analysis["profit_probability"] <= 100
    assert 0 <= analysis["all_hit_probability"] <= 100


@given(st.text(max_size=100))
def test_normalization_is_idempotent(value):
    assert canonical_person_key(canonical_person_key(value)) == canonical_person_key(value)
    assert canonical_matchup_key(canonical_matchup_key(value)) == canonical_matchup_key(value)
    assert canonical_stat_label(canonical_stat_label(value)) == canonical_stat_label(value)
