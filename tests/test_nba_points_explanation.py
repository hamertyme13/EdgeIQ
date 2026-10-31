from fastapi import HTTPException

from web.application.nba_points_explanation import build_nba_points_explanation
from web.routers.players import nba_points_explanation


def _research(*_args):
    return {
        "line": 24.5,
        "forecast": {"source": "market_prior", "projection": 24.5},
        "nba_points_intelligence": {
            "data_reliability": {"accepted_sources": {"espn": 2}},
            "projection": {"source": "market_prior", "expected_points": None},
            "thresholds": {
                "verified_season": {
                    "games": 2,
                    "custom_line": {"hits": 2, "decisions": 2, "pushes": 0, "hit_rate": 100.0},
                },
            },
            "matchup": {"opponent": None, "team_points_allowed": {"sample_size": 0}},
        },
    }


def test_explanation_uses_verified_games_and_separates_history_from_prediction():
    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "detailed", research=_research,
        prioritize=lambda facts: [fact["id"] for fact in reversed(facts)],
    )

    assert result["source"] == "ollama_prioritized"
    assert any("2 of 2 decided regular-season games" in bullet for bullet in result["bullets"])
    assert any("past frequency, not the next-game probability" in bullet for bullet in result["bullets"])
    assert any("independent points forecast is unavailable" in bullet for bullet in result["bullets"])
    assert not any("100.0" in bullet for bullet in result["bullets"])
    assert result["model_changed"] is False
    assert result["fact_details"][0]["evidence"]


def test_conflicting_finals_cannot_leak_general_forecast_into_explanation():
    def conflicting(*_args):
        payload = _research()
        payload["forecast"] = {"source": "verified_history_distribution", "projection": 26.1}
        payload["nba_points_intelligence"]["projection"] = {
            "source": "verified_history_distribution", "expected_points": None,
        }
        return payload

    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "detailed", research=conflicting,
        prioritize=lambda facts: [fact["id"] for fact in facts],
    )
    assert any("independent points forecast is unavailable" in fact for fact in result["bullets"])
    assert not any("26.1" in fact for fact in result["bullets"])


def test_verified_forecast_has_separate_model_evidence():
    def verified(*_args):
        payload = _research()
        payload["nba_points_intelligence"]["projection"] = {
            "source": "verified_history_distribution", "expected_points": 26.1,
            "model_version": "nba-points-v1",
        }
        return payload

    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "detailed", research=verified,
        prioritize=lambda facts: [fact["id"] for fact in facts],
    )
    forecast = next(fact for fact in result["fact_details"] if fact["id"] == "forecast")
    assert "26.1" in forecast["text"]
    assert forecast["evidence"] == "EdgeIQ forecast nba-points-v1"


def test_verified_opponent_pace_is_descriptive_and_sourced():
    def with_pace(*_args):
        payload = _research()
        payload["nba_points_intelligence"]["matchup"] = {
            "opponent": "NYK",
            "team_points_allowed": {
                "sample_size": 2, "last_10": 102.5,
                "pace_sample_size": 2, "pace_last_5": 98.4,
            },
        }
        return payload

    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "detailed", research=with_pace,
        prioritize=lambda facts: [fact["id"] for fact in facts],
    )
    pace = next(fact for fact in result["fact_details"] if fact["id"] == "pace")
    assert "98.4" in pace["text"]
    assert "not a player points adjustment" in pace["text"]
    assert pace["evidence"] == "ESPN official team box scores"


def test_invalid_model_order_falls_back_and_concise_keeps_market_limit():
    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "concise", research=_research,
        prioritize=lambda _facts: ["invented"],
    )

    assert result["source"] == "deterministic_fallback"
    assert len(result["bullets"]) == 3
    assert "validated expected value are unavailable" in result["bullets"][-1]


def test_concise_explanation_keeps_history_forecast_and_value_caveat_without_ollama():
    def should_not_call(_facts):
        raise AssertionError("Concise explanation should not wait for Ollama ordering")

    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "concise", research=_research,
        prioritize=should_not_call,
    )
    assert [fact["id"] for fact in result["fact_details"]] == ["hit_rate", "forecast", "market"]
    assert "past frequency, not the next-game probability" in result["bullets"][0]
    assert result["source"] == "deterministic_fallback"


def test_defense_percentile_is_sourced_context_not_player_probability():
    def with_rank(*_args):
        payload = _research()
        payload["nba_points_intelligence"]["matchup"] = {
            "opponent": "NYK",
            "team_points_allowed": {
                "sample_size": 7, "last_10": 112.5,
                "defensive_rank": 10, "ranked_teams": 12, "advantage_score": 82,
            },
        }
        return payload

    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "detailed", research=with_rank,
        prioritize=lambda facts: [fact["id"] for fact in facts],
    )
    fact = next(fact for fact in result["fact_details"] if fact["id"] == "defense_rank")
    assert "10 of 12" in fact["text"]
    assert "not this player's chance" in fact["text"]
    assert "Official pregame NBA team finals" in fact["evidence"]


def test_explanation_links_only_exact_official_team_games():
    def with_links(*_args):
        payload = _research()
        payload["nba_points_intelligence"]["matchup"] = {
            "opponent": "NYK",
            "team_points_allowed": {
                "sample_size": 7, "last_10": 112.5,
                "source_games": [
                    {"url": "https://www.espn.com/game/_/gameId/401234567"},
                    {"url": "https://www.espn.com/game/_/gameId/401234567"},
                    {"url": "javascript:alert(1)"},
                    {"url": "https://www.espn.com.evil.test/game/_/gameId/1"},
                    {"url": "https://www.espn.com/game/_/gameId/2?redirect=bad"},
                    {"url": "https://[broken"},
                ],
            },
        }
        return payload

    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "detailed", research=with_links,
        prioritize=lambda facts: [fact["id"] for fact in facts],
    )
    defense = next(fact for fact in result["fact_details"] if fact["id"] == "defense")
    assert defense["source_links"] == [
        {"label": "ESPN game 1", "url": "https://www.espn.com/game/_/gameId/401234567"}
    ]
    history = next(fact for fact in result["fact_details"] if fact["id"] == "history")
    assert history["source_links"] == []


def test_missing_exact_research_fails_closed_without_model():
    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "concise", research=lambda *_: {"line": 25.5},
        prioritize=lambda _facts: [],
    )
    assert result["status"] == "unavailable"


def test_route_validates_detail_without_running_research():
    try:
        nba_points_explanation("Sample Player", 24.5, detail="invalid")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Invalid detail should be rejected")
