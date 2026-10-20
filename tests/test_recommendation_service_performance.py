from web.application.recommendation_service import (
    entry_suggestions_payload,
    generator_games_payload,
    trending_props_payload,
)


def test_generator_games_lists_only_same_day_identifiable_provider_matchups() -> None:
    props = [
        {"league": "WNBA", "game": "Aces vs Storm", "game_time": "2026-10-15T23:00:00Z", "player": "A"},
        {"league": "WNBA", "game": "Storm @ Aces", "game_time": "2026-10-15T23:00:00Z", "player": "B"},
        {"league": "WNBA", "game": "Fever vs Liberty", "game_time": "2026-10-15T23:00:00Z", "player": "C"},
        {"league": "WNBA", "game": "Fever", "game_time": "2026-10-15T23:00:00Z", "player": "D"},
    ]
    result = generator_games_payload(
        "WNBA", "PrizePicks",
        fetch_props=lambda *args: props,
        props_by_platform=lambda platform, rows: [(object(), rows[:3])],
    )
    assert {game["key"] for game in result["games"]} == {"WNBA|ACES@STORM", "WNBA|FEVER@LIBERTY"}
    assert sum(game["prop_count"] for game in result["games"]) == 3
    assert {game["key"]: game["player_count"] for game in result["games"]} == {
        "WNBA|ACES@STORM": 2, "WNBA|FEVER@LIBERTY": 1,
    }


def test_generator_game_and_direction_filter_reach_only_selected_candidates() -> None:
    props = [
        {"platform": "PrizePicks", "league": "WNBA", "game": game,
         "game_time": "2026-10-15T23:00:00Z", "player": player, "stat": "Points", "line": 10.5}
        for game, player in (("Aces vs Storm", "A"), ("Aces vs Storm", "B"),
                             ("Fever vs Liberty", "C"), ("Fever vs Liberty", "D"),
                             ("Dream vs Mystics", "E"))
    ]
    calls = []

    def suggest(rows, *args, **kwargs):
        calls.append((rows, kwargs))
        return []

    kwargs = {
        "canonical_platform": lambda value: value,
        "entry_platforms": {"PrizePicks"},
        "cached_briefing": lambda *args: {},
        "fetch_props": lambda *args: props,
        "props_by_platform": lambda platform, rows: [(object(), rows)] if rows else [],
        "mixed_risk": lambda *args: [],
        "suggest": suggest,
        "serialize_suggestion": lambda value: value,
    }
    result = entry_suggestions_payload(
        "WNBA", "PrizePicks", 2, game_key="WNBA|ACES@STORM", direction_filter="Under", **kwargs,
    )
    assert result["game_key"] == "WNBA|ACES@STORM"
    assert [row["player"] for row in calls[0][0]] == ["A", "B"]
    assert calls[0][1]["direction_filter"] == "Under"
    calls.clear()
    mixed = entry_suggestions_payload(
        "WNBA", "PrizePicks", 2,
        game_key="WNBA|ACES@STORM,WNBA|FEVER@LIBERTY", direction_filter="Over", **kwargs,
    )
    assert mixed["game_keys"] == ["WNBA|ACES@STORM", "WNBA|FEVER@LIBERTY"]
    assert [row["player"] for row in calls[0][0]] == ["A", "B", "C", "D"]
    calls.clear()
    stale = entry_suggestions_payload(
        "WNBA", "PrizePicks", 2, game_key="WNBA|UNKNOWN@TEAM", direction_filter="Over", **kwargs,
    )
    assert stale["suggestions"] == []
    assert calls == []


def test_gaming_markets_are_visible_but_not_graded_as_paid_recommendations() -> None:
    result = trending_props_payload(
        "PrizePicks",
        "CS2",
        15,
        fetch_props=lambda *args: [{
            "platform": "PrizePicks",
            "player": "device",
            "league": "CS2",
            "stat": "MAPS 1-2 Kills",
            "line": 27.5,
            "game": "Astralis vs Liquid",
            "game_time": "2026-08-24T18:00:00Z",
            "trending_count": 5000,
            "research_only": True,
        }],
        analyze_prop=lambda prop: (_ for _ in ()).throw(AssertionError("research rows must not be modeled")),
        end_to_end_eligibility=lambda prop: {
            "eligible": False,
            "reasons": ["verified esports results source is not connected"],
        },
    )

    assert result["mode"] == "provider_market_research"
    assert result["research_only"] is True
    assert result["props"][0]["player"] == "device"
    assert result["props"][0]["forecast_paid_eligible"] is False
    assert result["props"][0]["end_to_end_confirmed"] is False


def test_gaming_entry_generator_prevents_unsettleable_cards() -> None:
    result = entry_suggestions_payload(
        "CS2",
        "Underdog",
        3,
        canonical_platform=lambda value: value,
        entry_platforms={"PrizePicks", "Underdog"},
        cached_briefing=lambda *args: (_ for _ in ()).throw(AssertionError("briefing should not run")),
        fetch_props=lambda *args: (_ for _ in ()).throw(AssertionError("provider generator should not run")),
        props_by_platform=lambda *args: [],
        mixed_risk=lambda *args: [],
        suggest=lambda *args, **kwargs: [],
        serialize_suggestion=lambda value: value,
    )

    assert result["suggestions"] == []
    assert result["mode"] == "esports_research_only"
    assert "preventing stuck entries" in result["message"]


def test_sleeper_generator_explains_missing_pickem_feed(monkeypatch) -> None:
    monkeypatch.delenv("EDGEIQ_SLEEPER_PROPS_URL", raising=False)
    monkeypatch.delenv("EDGEIQ_SLEEPER_PROPS_FILE", raising=False)
    monkeypatch.delenv("EDGEIQ_SLEEPER_APIFY_ENABLED", raising=False)
    result = entry_suggestions_payload(
        "NFL", "Sleeper", 3,
        canonical_platform=lambda value: value,
        entry_platforms={"PrizePicks", "Underdog", "Sleeper"},
        cached_briefing=lambda *args: {},
        fetch_props=lambda *args: [],
        props_by_platform=lambda *args: [],
        mixed_risk=lambda *args: [],
        suggest=lambda *args, **kwargs: [],
        serialize_suggestion=lambda value: value,
    )

    assert result["suggestions"] == []
    assert result["mode"] == "sleeper_feed_unavailable"
    assert "not current Pick'em lines" in result["message"]


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
        suggest=lambda *args, **kwargs: [object()],
        serialize_suggestion=lambda value: {"entry": {"props": []}},
    )

    assert calls["fetch"] == 0
    assert result["performance"]["source"] == "daily_briefing_snapshot"


def test_entry_generator_retries_live_board_when_briefing_cannot_build_card() -> None:
    calls = {"fetch": 0, "suggest": 0}
    briefing_props = [
        {"platform": "PrizePicks", "player": player, "sport": "WNBA", "stat": "Points", "line": 10.5}
        for player in ("A", "B", "C")
    ]

    def fetch(*args):
        calls["fetch"] += 1
        return [{**row, "projection": 12.0} for row in briefing_props]

    def suggest(*args, **kwargs):
        calls["suggest"] += 1
        return [] if calls["suggest"] == 1 else [object()]

    result = entry_suggestions_payload(
        "WNBA", "PrizePicks", 3,
        canonical_platform=lambda value: value,
        entry_platforms={"PrizePicks"},
        cached_briefing=lambda *args: {
            "platform": "PrizePicks", "cache": {"stale": False},
            "top_opportunities": briefing_props,
        },
        fetch_props=fetch,
        props_by_platform=lambda platform, rows: [(object(), rows)],
        mixed_risk=lambda *args: [],
        suggest=suggest,
        serialize_suggestion=lambda value: {"entry": {"props": []}},
    )

    assert calls == {"fetch": 1, "suggest": 2}
    assert result["performance"]["source"] == "live_provider_fallback"


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
