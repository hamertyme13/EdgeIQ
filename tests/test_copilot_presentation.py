from web.application.copilot_presentation import quantitative_facts


def test_briefing_facts_are_source_linked_and_bounded():
    bundle = {
        "intent": "daily_briefing",
        "summary": {"top_opportunities": [
            {"player": "A", "line": 19.5, "projection": 21.2, "confidence": 61.0},
            {"player": "B", "line": "not a number", "confidence": float("nan")},
            {"player": "C", "line": 8.5},
            {"player": "D", "line": 7.5},
        ]},
    }
    facts = quantitative_facts(bundle)
    assert [(row["subject"], row["label"], row["value"]) for row in facts] == [
        ("A", "Line", 19.5), ("A", "Model projection", 21.2),
        ("A", "Displayed confidence", 61.0), ("C", "Line", 8.5),
    ]
    assert all(row["citation_id"] == "briefing-snapshot" for row in facts)


def test_player_facts_do_not_use_requested_line_as_provider_line():
    bundle = {"intent": "player_research", "summary": {
        "query_context": {"player": "Example", "requested_line": 20.5},
        "recommendation": {"line": 21.5, "projection": 22.0},
    }}
    assert [row["value"] for row in quantitative_facts(bundle)] == [21.5, 22.0]
    assert quantitative_facts({"intent": "portfolio", "summary": {"pending_entries": 3}}) == []
