from fastapi import HTTPException

from web.application.nba_points_explanation import build_nba_points_explanation
from web.routers.players import nba_points_explanation


def _research(*_args):
    return {
        "line": 24.5,
        "forecast": {"source": "market_prior", "projection": 24.5},
        "nba_points_intelligence": {
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


def test_invalid_model_order_falls_back_and_concise_keeps_market_limit():
    result = build_nba_points_explanation(
        "Sample Player", 24.5, "PrizePicks", "concise", research=_research,
        prioritize=lambda _facts: ["invented"],
    )

    assert result["source"] == "deterministic_fallback"
    assert len(result["bullets"]) == 3
    assert "validated expected value are unavailable" in result["bullets"][-1]


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
