from web.application.recommendation_service import entry_suggestions_payload


def test_entry_generator_reuses_identical_short_lived_result() -> None:
    calls = {"suggest": 0}
    props = [
        {"platform": "PrizePicks", "player": "A", "stat": "Points", "line": 10.5, "direction": "Over"},
        {"platform": "PrizePicks", "player": "B", "stat": "Rebounds", "line": 5.5, "direction": "Over"},
    ]

    def suggest(*args, **kwargs):
        calls["suggest"] += 1
        return []

    kwargs = {
        "canonical_platform": lambda value: value,
        "entry_platforms": {"PrizePicks"},
        "cached_briefing": lambda *args: {},
        "fetch_props": lambda *args: props,
        "props_by_platform": lambda platform, rows: [(object(), rows)],
        "mixed_risk": lambda *args: [],
        "suggest": suggest,
        "serialize_suggestion": lambda value: value,
    }
    first = entry_suggestions_payload("WNBA", "PrizePicks", 2, **kwargs)
    second = entry_suggestions_payload("WNBA", "PrizePicks", 2, **kwargs)

    assert calls["suggest"] == 1
    assert first["performance"]["cache_hit"] is False
    assert second["performance"]["cache_hit"] is True
