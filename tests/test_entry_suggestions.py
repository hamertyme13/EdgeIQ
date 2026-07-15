from analytics.entry_suggestions import suggest_entries
from models.platform import Platform


def test_suggest_entries_returns_ranked_sport_specific_entries():
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
        {"player": "D", "team": "DDD", "league": "NBA", "stat": "Points", "line": 24.5, "trending_count": 70000},
    ]

    suggestions = suggest_entries(raw_props, "WNBA", Platform.PRIZEPICKS, limit=5)

    assert [suggestion.rank for suggestion in suggestions] == [1, 2, 3]
    assert all(prop.player.sport == "WNBA" for suggestion in suggestions for prop in suggestion.entry.props)
    assert suggestions[0].score >= suggestions[-1].score


def test_suggest_entries_can_recommend_under_legs_without_explicit_projection():
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Rebounds", "line": 8.5, "trending_count": 80000},
    ]

    suggestions = suggest_entries(raw_props, "WNBA", Platform.PRIZEPICKS, limit=3)

    directions = {prop.direction for suggestion in suggestions for prop in suggestion.entry.props}
    assert "Under" in directions


def test_suggest_entries_uses_unique_players():
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Rebounds", "line": 9.5, "trending_count": 90000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 80000},
    ]

    suggestions = suggest_entries(raw_props, "WNBA", Platform.PRIZEPICKS, limit=5)

    assert len(suggestions) == 1
    assert {prop.player.name for prop in suggestions[0].entry.props} == {"A", "B"}


def test_suggest_entries_can_build_three_leg_parlays():
    raw_props = [
        {"player": "A", "team": "AAA", "league": "MLB", "stat": "Hits", "line": 1.5, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "MLB", "stat": "Runs", "line": 0.5, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "MLB", "stat": "RBIs", "line": 0.5, "trending_count": 80000},
        {"player": "D", "team": "DDD", "league": "MLB", "stat": "Hits", "line": 1.5, "trending_count": 70000},
    ]

    suggestions = suggest_entries(raw_props, "MLB", Platform.PRIZEPICKS, limit=2, leg_count=3)

    assert [suggestion.rank for suggestion in suggestions] == [1, 2]
    assert all(len(suggestion.entry.props) == 3 for suggestion in suggestions)
