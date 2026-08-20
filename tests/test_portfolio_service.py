from datetime import UTC, datetime

from web.application.portfolio_service import (
    active_portfolio_monitor_payload,
    portfolio_intelligence_payload,
    portfolio_ranked_suggestions,
    refresh_portfolio_market_payload,
)


def _prop(player: str, game: str, confidence: float = 70.0) -> dict:
    return {
        "player": player,
        "team": player,
        "sport": "WNBA",
        "stat": "Points",
        "direction": "Over",
        "line": 20.5,
        "confidence": confidence,
        "edge": 1.5,
        "platform": "PrizePicks",
        "game": game,
    }


def test_portfolio_intelligence_reports_player_game_and_market_concentration():
    pending = [
        {"id": 1, "entry_mode": "real", "wager": 10, "props": [_prop("A", "AAA @ BBB"), _prop("B", "AAA @ BBB")]},
        {"id": 2, "entry_mode": "real", "wager": 15, "props": [_prop("A", "AAA @ BBB"), _prop("C", "CCC @ DDD")]},
        {"id": 3, "entry_mode": "paper", "wager": 0, "props": [_prop("A", "AAA @ BBB")]},
    ]

    payload = portfolio_intelligence_payload(
        pending_entries=pending,
        bankroll=500,
        strategy={
            "max_player_entries": 1,
            "max_game_entries": 1,
            "max_market_entries": 1,
            "max_open_exposure_pct": 15,
        },
    )

    assert payload["status"] == "Concentrated"
    assert payload["pending_real_entries"] == 2
    assert payload["pending_paper_entries"] == 1
    assert payload["open_wager"] == 25
    assert payload["bankroll_exposure_pct"] == 5.0
    assert any(row["dimension"] == "market" and row["label"].startswith("A Over") for row in payload["concentrations"])
    assert payload["top_players"][0]["label"] == "A"
    assert payload["top_teams"]
    assert payload["directions"][0]["label"] == "Over"
    assert payload["correlation_score"] > 0
    assert payload["shared_leg_failure_risk"]["repeated_props"] == 1


def test_portfolio_ranking_prefers_lower_exposure_and_offers_replacement():
    pending = [
        {"id": 1, "entry_mode": "real", "wager": 10, "props": [_prop("A", "AAA @ BBB")]},
    ]
    concentrated = {
        "score": 90,
        "value_adjusted_score": 90,
        "entry": {"props": [_prop("A", "AAA @ BBB", 72), _prop("B", "CCC @ DDD", 70)]},
    }
    diversified = {
        "score": 86,
        "value_adjusted_score": 86,
        "entry": {"props": [_prop("C", "EEE @ FFF", 69), _prop("D", "GGG @ HHH", 68)]},
    }

    ranked = portfolio_ranked_suggestions(
        [concentrated, diversified],
        pending_entries=pending,
        strategy={"max_player_entries": 1, "max_game_entries": 2, "max_market_entries": 1},
        limit=2,
    )

    assert ranked[0]["entry"]["props"][0]["player"] == "C"
    assert ranked[0]["portfolio"]["risk"] == "Low"
    assert ranked[1]["portfolio"]["risk"] == "High"
    assert ranked[1]["portfolio"]["replacements"]
    assert ranked[1]["portfolio"]["replacements"][0]["add"]["player"] in {"C", "D"}


def test_portfolio_ranking_penalizes_shared_legs_across_generated_batch():
    shared = {
        "score": 90,
        "value_adjusted_score": 90,
        "entry": {"props": [_prop("A", "AAA @ BBB"), _prop("B", "CCC @ DDD")]},
    }
    repeated = {
        "score": 89,
        "value_adjusted_score": 89,
        "entry": {"props": [_prop("A", "AAA @ BBB"), _prop("C", "EEE @ FFF")]},
    }
    varied = {
        "score": 86,
        "value_adjusted_score": 86,
        "entry": {"props": [_prop("D", "GGG @ HHH"), _prop("E", "III @ JJJ")]},
    }

    ranked = portfolio_ranked_suggestions(
        [shared, repeated, varied],
        pending_entries=[],
        strategy={"max_player_entries": 2, "max_game_entries": 3, "max_market_entries": 1},
        limit=3,
    )

    assert ranked[0]["entry"]["props"][0]["player"] == "A"
    assert ranked[1]["entry"]["props"][0]["player"] == "D"
    assert ranked[2]["portfolio"]["batch_shared_legs"] == 1


def test_active_monitor_flags_adverse_paid_card_and_ignores_paper():
    pending = [
        {
            "id": 11,
            "entry_mode": "real",
            "platform": "PrizePicks",
            "wager": 10,
            "placed_at": "2026-08-08T12:00:00Z",
            "props": [
                {**_prop("A", "AAA @ BBB"), "game_time": "2026-08-08T20:00:00Z"},
                {**_prop("B", "CCC @ DDD"), "game_time": "2026-08-08T21:00:00Z"},
            ],
        },
        {"id": 12, "entry_mode": "paper", "platform": "PrizePicks", "props": [_prop("C", "EEE @ FFF")]},
    ]
    market = [{
        "id": 11,
        "legs": [
            {"player": "A", "placed_line": 20.5, "current_line": 19.5, "clv": -1.0, "reliable": True},
            {"player": "B", "placed_line": 20.5, "current_line": 19.0, "clv": -1.5, "reliable": True},
        ],
    }]

    payload = active_portfolio_monitor_payload(
        pending_entries=pending,
        market_entries=market,
        now=datetime(2026, 8, 8, 16, tzinfo=UTC),
    )

    assert payload["count"] == 1
    assert payload["action_count"] == 1
    assert payload["entries"][0]["status"] == "Review"
    assert payload["entries"][0]["adverse_legs"] == 2
    assert payload["entries"][0]["average_line_value"] == -1.25


def test_active_monitor_locks_started_entry_instead_of_giving_pregame_advice():
    pending = [{
        "id": 21,
        "entry_mode": "real",
        "platform": "Underdog",
        "wager": 5,
        "props": [{**_prop("A", "AAA @ BBB"), "game_time": "2026-08-08T18:00:00Z"}],
    }]
    market = [{
        "id": 21,
        "legs": [{"player": "A", "placed_line": 20.5, "current_line": 19.5, "clv": -1.0, "reliable": True}],
    }]

    payload = active_portfolio_monitor_payload(
        pending_entries=pending,
        market_entries=market,
        now=datetime(2026, 8, 8, 19, tzinfo=UTC),
    )

    assert payload["entries"][0]["status"] == "Locked"
    assert payload["entries"][0]["legs"][0]["game_state"] == "Live"
    assert "avoid duplicating" in payload["entries"][0]["action"]


def test_active_monitor_moves_old_unsettled_game_to_awaiting_result():
    pending = [{
        "id": 22,
        "entry_mode": "real",
        "platform": "PrizePicks",
        "wager": 5,
        "props": [{**_prop("A", "AAA @ BBB"), "game_time": "2026-08-08T18:00:00Z"}],
    }]

    payload = active_portfolio_monitor_payload(
        pending_entries=pending,
        market_entries=[{"id": 22, "legs": []}],
        now=datetime(2026, 8, 9, 2, tzinfo=UTC),
    )

    assert payload["entries"][0]["status"] == "Locked"
    assert payload["entries"][0]["legs"][0]["game_state"] == "Awaiting Result"


def test_market_refresh_targets_only_providers_on_pending_paid_entries():
    calls = []
    pending = [
        {
            "id": 31,
            "entry_mode": "real",
            "platform": "PrizePicks",
            "props": [{**_prop("A", "AAA @ BBB"), "platform": "PrizePicks"}],
        },
        {
            "id": 32,
            "entry_mode": "real",
            "platform": "Underdog",
            "props": [{**_prop("B", "CCC @ DDD"), "platform": "Underdog"}],
        },
        {
            "id": 33,
            "entry_mode": "paper",
            "platform": "Sleeper",
            "props": [{**_prop("C", "EEE @ FFF"), "platform": "Sleeper"}],
        },
    ]

    result = refresh_portfolio_market_payload(
        pending_entries=pending,
        fetch_platform_props=lambda platform, force_refresh: calls.append((platform, force_refresh)) or [{}],
        intelligence=lambda: {"monitor": {"status_counts": {}}},
    )

    assert calls == [("PrizePicks", True), ("Underdog", True)]
    assert result["pending_paid_entries"] == 2
    assert all(row["status"] == "refreshed" for row in result["providers"])
    assert "Portfolio lines are current" in result["message"]


def test_market_refresh_explains_when_exact_line_match_is_still_missing():
    result = refresh_portfolio_market_payload(
        pending_entries=[{
            "id": 41,
            "entry_mode": "real",
            "platform": "PrizePicks",
            "props": [{**_prop("A", "AAA @ BBB"), "platform": "PrizePicks"}],
        }],
        fetch_platform_props=lambda platform, force_refresh: [{"player": "A"}],
        intelligence=lambda: {"monitor": {"status_counts": {"Needs Refresh": 1}}},
    )

    assert "still needs an exact same-game line match" in result["message"]


def test_market_refresh_explains_closed_lines_for_locked_entries():
    result = refresh_portfolio_market_payload(
        pending_entries=[{
            "id": 42,
            "entry_mode": "real",
            "platform": "PrizePicks",
            "props": [{**_prop("A", "AAA @ BBB"), "platform": "PrizePicks"}],
        }],
        fetch_platform_props=lambda platform, force_refresh: [{"player": "A"}],
        intelligence=lambda: {
            "monitor": {
                "status_counts": {"Locked": 1},
                "entries": [{"unavailable_legs": 2}],
            },
        },
    )

    assert "2 live or completed offers are now closed" in result["message"]
    assert "settlement completes" in result["message"]
