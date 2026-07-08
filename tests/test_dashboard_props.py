from gui.tabs.dashboard_tab import _unique_player_props


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
