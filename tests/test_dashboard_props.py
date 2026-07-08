from gui.tabs.dashboard_tab import _top_props_by_sport, _unique_player_props


def test_unique_player_props_keeps_highest_ranked_prop_per_player():
    props = [
        {"player": "A", "trending_count": 100, "stat": "Points"},
        {"player": "B", "trending_count": 90, "stat": "Assists"},
        {"player": "A", "trending_count": 80, "stat": "Rebounds"},
        {"player": "C", "trending_count": 70, "stat": "Points"},
    ]

    result = _unique_player_props(props, limit=3)

    assert [prop["player"] for prop in result] == ["A", "B", "C"]
    assert result[0]["stat"] == "Points"


def test_unique_player_props_treats_player_names_case_insensitively():
    props = [
        {"player": "Caitlin Clark", "trending_count": 100},
        {"player": "caitlin clark", "trending_count": 90},
        {"player": "A'ja Wilson", "trending_count": 80},
    ]

    result = _unique_player_props(props, limit=25)

    assert [prop["player"] for prop in result] == ["Caitlin Clark", "A'ja Wilson"]


def test_top_props_by_sport_returns_five_unique_players_per_sport():
    props = [
        {"player": f"W{i}", "league": "WNBA", "trending_count": 100 - i}
        for i in range(7)
    ] + [
        {"player": f"M{i}", "league": "MLB", "trending_count": 90 - i}
        for i in range(7)
    ]
    props.sort(key=lambda prop: prop["trending_count"], reverse=True)

    result = _top_props_by_sport(props, limit=5)

    assert len([prop for prop in result if prop["league"] == "WNBA"]) == 5
    assert len([prop for prop in result if prop["league"] == "MLB"]) == 5
    assert {prop["sport_rank"] for prop in result if prop["league"] == "WNBA"} == {1, 2, 3, 4, 5}
