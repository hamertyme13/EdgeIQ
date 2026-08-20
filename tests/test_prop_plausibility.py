from utils.prop_plausibility import prop_line_plausibility


def test_rejects_implausible_mlb_hits_market():
    result = prop_line_plausibility({"sport": "MLB", "stat": "Hits", "line": 8.5})

    assert result.valid is False
    assert "outside the supported market range" in result.reason


def test_accepts_normal_and_broad_alternate_markets():
    assert prop_line_plausibility({"sport": "MLB", "stat": "Hits", "line": 1.5}).valid
    assert prop_line_plausibility({"sport": "WNBA", "stat": "PRA", "line": 54.5}).valid
    assert prop_line_plausibility({"sport": "NFL", "stat": "Passing Yards", "line": 325.5}).valid


def test_unbounded_supported_future_stat_is_not_guessed_at():
    result = prop_line_plausibility({"sport": "TENNIS", "stat": "Aces", "line": 24.5})

    assert result.valid is True
    assert result.maximum is None


def test_missing_line_is_rejected_at_persistence_validation():
    result = prop_line_plausibility({"sport": "NFL", "stat": "Passing Yards"})

    assert result.valid is False
    assert "numeric" in result.reason


def test_nhl_market_ranges_accept_normal_lines_and_reject_contract_mismatches():
    assert prop_line_plausibility({"sport": "NHL", "stat": "Shots on Goal", "line": 3.5}).valid
    assert prop_line_plausibility({"sport": "NHL", "stat": "Goalie Saves", "line": 27.5}).valid
    assert not prop_line_plausibility({"sport": "NHL", "stat": "Goals", "line": 29.5}).valid
