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


def test_entry_generator_prefers_fresh_briefing_snapshot() -> None:
    calls = {"fetch": 0}
    briefing_props = [
        {
            "platform": "PrizePicks", "player": player, "sport": "WNBA",
            "stat": "Points", "line": 10.5 + index, "direction": "Over", "projection": 12.0 + index,
        }
        for index, player in enumerate(("A", "B", "C"))
    ]

    def fetch(*args):
        calls["fetch"] += 1
        return []

    result = entry_suggestions_payload(
        "WNBA", "PrizePicks", 3,
        canonical_platform=lambda value: value,
        entry_platforms={"PrizePicks"},
        cached_briefing=lambda *args: {
            "platform": "PrizePicks",
            "cache": {"stale": False},
            "top_opportunities": briefing_props,
        },
        fetch_props=fetch,
        props_by_platform=lambda platform, rows: [(object(), rows)],
        mixed_risk=lambda *args: [],
        suggest=lambda *args, **kwargs: [],
        serialize_suggestion=lambda value: value,
    )

    assert calls["fetch"] == 0
    assert result["performance"]["source"] == "daily_briefing_snapshot"


def test_entry_generator_falls_back_when_briefing_has_too_few_players() -> None:
    calls = {"fetch": 0}

    def fetch(*args):
        calls["fetch"] += 1
        return [
            {"platform": "PrizePicks", "player": player, "stat": "Points", "line": 10.5, "direction": "Over"}
            for player in ("A", "B", "C")
        ]

    result = entry_suggestions_payload(
        "WNBA", "PrizePicks", 3,
        canonical_platform=lambda value: value,
        entry_platforms={"PrizePicks"},
        cached_briefing=lambda *args: {
            "platform": "PrizePicks", "cache": {"stale": False},
            "top_opportunities": [{"platform": "PrizePicks", "player": "A", "sport": "WNBA", "stat": "Points", "line": 10.5}],
        },
        fetch_props=fetch,
        props_by_platform=lambda platform, rows: [(object(), rows)],
        mixed_risk=lambda *args: [],
        suggest=lambda *args, **kwargs: [],
        serialize_suggestion=lambda value: value,
    )

    assert calls["fetch"] == 1
    assert result["performance"]["source"] == "live_provider_board"
