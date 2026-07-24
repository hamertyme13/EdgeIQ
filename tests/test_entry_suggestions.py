import analytics.entry_suggestions as suggestions_module
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

    assert [suggestion.rank for suggestion in suggestions] == [1, 2, 3, 4, 5]
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


def test_suggest_entries_keeps_multiple_markets_but_not_duplicate_players():
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 100000},
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Rebounds", "line": 9.5, "projection": 12.5, "trending_count": 90000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Assists", "line": 7.5, "trending_count": 80000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Points", "line": 14.5, "trending_count": 70000},
    ]

    suggestions = suggest_entries(raw_props, "WNBA", Platform.PRIZEPICKS, limit=5)

    assert suggestions
    assert all(
        len([prop.player.name for prop in suggestion.entry.props])
        == len({prop.player.name for prop in suggestion.entry.props})
        for suggestion in suggestions
    )
    assert {
        prop.stat.value
        for suggestion in suggestions
        for prop in suggestion.entry.props
        if prop.player.name == "A"
    } >= {"Points", "Rebounds"}


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


def test_provider_backed_projection_scores_above_auto_projected_when_edge_matches():
    raw_props = [
        {"player": "A", "team": "AAA", "league": "WNBA", "stat": "Points", "line": 20.5, "projection": 22.0, "trending_count": 100000},
        {"player": "B", "team": "BBB", "league": "WNBA", "stat": "Points", "line": 20.5, "projection": 22.0, "trending_count": 90000},
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 80000},
        {"player": "D", "team": "DDD", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 70000},
        {"player": "E", "team": "EEE", "league": "WNBA", "stat": "Points", "line": 20.5, "trending_count": 60000},
    ]

    suggestions = suggest_entries(raw_props, "WNBA", Platform.PRIZEPICKS, limit=1, leg_count=2)

    assert suggestions
    assert all(not prop.auto_projected for prop in suggestions[0].entry.props)
    assert all(prop.projection_source == "confirmed_provider" for prop in suggestions[0].entry.props)


def test_generated_projection_keeps_auto_projected_provenance():
    raw_props = [
        {
            "player": name,
            "team": name,
            "league": "WNBA",
            "stat": "Points",
            "line": 20.5,
            "projection": 22.0,
            "auto_projected": True,
            "projection_source": "line_model",
            "confirmation": True,
        }
        for name in ("A", "B")
    ]

    suggestion = suggest_entries(raw_props, "WNBA", Platform.PRIZEPICKS, limit=1, leg_count=2)[0]

    assert all(prop.auto_projected for prop in suggestion.entry.props)
    assert all(prop.projection_source == "line_model" for prop in suggestion.entry.props)


def test_adjusted_prizepicks_lines_do_not_create_opposite_side_free_edges():
    raw_props = [
        {
            "player": "A",
            "team": "AAA",
            "league": "WNBA",
            "stat": "Rebounds",
            "line": 15.5,
            "baseline_line": 9.0,
            "standard_line": 9.0,
            "line_offer_type": "demon",
            "adjusted_line": True,
            "is_premium_line": True,
            "trending_count": 100000,
        },
        {
            "player": "B",
            "team": "BBB",
            "league": "WNBA",
            "stat": "Assists",
            "line": 6.5,
            "baseline_line": 8.0,
            "standard_line": 8.0,
            "line_offer_type": "goblin",
            "adjusted_line": True,
            "is_discounted_line": True,
            "trending_count": 90000,
        },
        {"player": "C", "team": "CCC", "league": "WNBA", "stat": "Points", "line": 17.5, "trending_count": 80000},
    ]

    suggestions = suggest_entries(raw_props, "WNBA", Platform.PRIZEPICKS, limit=3, leg_count=2)

    adjusted_sides = {
        (prop.player.name, prop.direction)
        for suggestion in suggestions
        for prop in suggestion.entry.props
        if prop.adjusted_line
    }
    assert ("A", "Under") not in adjusted_sides
    assert ("A", "Over") in adjusted_sides
    assert ("B", "Over") in adjusted_sides


def test_feedback_is_calculated_once_per_candidate_not_per_combination(monkeypatch):
    calls = {"history": 0, "adjustments": 0}
    history = [{"status": "Settled", "result": "Win"} for _ in range(5)]

    def feedback_history():
        calls["history"] += 1
        return history

    def adjustment(confidence, prop, entries):
        calls["adjustments"] += 1
        assert entries is history
        return 0.0

    monkeypatch.setattr(suggestions_module, "settled_feedback_entries", feedback_history)
    monkeypatch.setattr(suggestions_module, "feedback_adjustment", adjustment)
    raw_props = [
        {"player": f"Player {index}", "team": f"T{index}", "league": "WNBA", "stat": "Points", "line": 10.5 + index}
        for index in range(12)
    ]

    suggestions = suggest_entries(raw_props, "WNBA", Platform.PRIZEPICKS, limit=2, leg_count=5, apply_feedback=True)

    assert suggestions
    assert calls["history"] == 1
    assert calls["adjustments"] <= 18
