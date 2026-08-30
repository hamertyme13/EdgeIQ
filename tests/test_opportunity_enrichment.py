from services.opportunity_enrichment import role_opportunities


def test_basketball_scoring_uses_shot_volume() -> None:
    values = {"Minutes": 34, "Field Goals Attempted": 16, "Free Throws Attempted": 6}
    assert role_opportunities("WNBA", "Points", values) == 22
    assert role_opportunities("WNBA", "Rebounds", values) == 34


def test_nfl_markets_use_matching_workload() -> None:
    values = {
        "Passing Attempts": 31,
        "Rush Attempts": 14,
        "Targets": 9,
        "Kicking Field Goals Attempted": 3,
        "Extra Points Attempted": 4,
    }
    assert role_opportunities("NFL", "Passing Yards", values) == 31
    assert role_opportunities("NFL", "Rushing Yards", values) == 14
    assert role_opportunities("NFL", "Receiving Yards", values) == 9
    assert role_opportunities("NFL", "Field Goals Made", values) == 3
    assert role_opportunities("NFL", "Extra Points Made", values) == 4
    assert role_opportunities("NCAAF", "Passing Yards", values) == 31
    assert role_opportunities("NCAAF", "Receiving Yards", values) == 9
