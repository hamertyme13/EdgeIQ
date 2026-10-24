from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from web.application.nba_points_market import build_nba_points_market

NOW = datetime(2026, 10, 23, 16, tzinfo=UTC)


def _research(*_args):
    return {
        "active_props": [{
            "player": "Research Guard", "stat": "Points", "line": 19.5,
            "line_offer_type": "standard", "game": "BOS @ NYK", "team": "BOS",
            "game_time": "2026-10-23T23:00:00Z",
        }],
        "recommendation": {"line": 19.5, "game": "BOS @ NYK", "game_time": "2026-10-23T23:00:00Z"},
        "nba_points_intelligence": {"projection": {
            "source": "verified_history_distribution", "over_probability": 62.0,
        }},
    }


def _market(*_args):
    return {
        "available": True, "source": "The Odds API", "source_type": "multi_book_no_vig",
        "line": 19.5, "over_probability": 54.0, "under_probability": 46.0,
        "book_count": 3, "best_over_odds": -110, "best_under_odds": -105,
        "oldest_update": (NOW - timedelta(minutes=5)).isoformat(),
        "stale": False,
    }


def test_exact_market_comparison_is_research_only():
    result = build_nba_points_market(
        "Research Guard", 19.5, "PrizePicks", research=_research, market_lookup=_market, now=NOW,
    )

    assert result["status"] == "research_comparison"
    assert result["market_over_probability"] == 54.0
    assert result["model_market_gap"] == 8.0
    assert result["ev"] is None
    assert result["payout_verified"] is False


def test_exact_market_requires_current_matching_offer_before_odds_lookup():
    calls = []
    result = build_nba_points_market(
        "Research Guard", 20.5, "PrizePicks", research=_research,
        market_lookup=lambda *_args: calls.append(True), now=NOW,
    )
    assert result["status"] == "unavailable"
    assert calls == []


def test_exact_market_rejects_stale_or_different_line():
    stale = build_nba_points_market(
        "Research Guard", 19.5, "PrizePicks", research=_research,
        market_lookup=lambda *_args: {**_market(), "oldest_update": (NOW - timedelta(hours=2)).isoformat()}, now=NOW,
    )
    mismatch = build_nba_points_market(
        "Research Guard", 19.5, "PrizePicks", research=_research,
        market_lookup=lambda *_args: {**_market(), "line": 20.5}, now=NOW,
    )
    assert stale["status"] == mismatch["status"] == "unavailable"
    assert stale["market_over_probability"] is None
    assert mismatch["model_market_gap"] is None


def test_market_prior_does_not_create_model_gap():
    def prior(*_args):
        payload = _research()
        payload["nba_points_intelligence"]["projection"] = {
            "source": "market_prior", "over_probability": 62.0,
        }
        return payload

    result = build_nba_points_market(
        "Research Guard", 19.5, "PrizePicks", research=prior, market_lookup=_market, now=NOW,
    )
    assert result["market_over_probability"] == 54.0
    assert result["model_over_probability"] is None
    assert result["model_market_gap"] is None


def test_forecast_from_another_game_does_not_create_model_gap():
    def different_game(*_args):
        payload = _research()
        payload["recommendation"] = {**payload["recommendation"], "game_time": "2026-10-24T23:00:00Z"}
        return payload

    result = build_nba_points_market(
        "Research Guard", 19.5, "PrizePicks", research=different_game, market_lookup=_market, now=NOW,
    )
    assert result["market_over_probability"] == 54.0
    assert result["model_over_probability"] is None


def test_nba_points_market_route_uses_player_dependencies(monkeypatch):
    from web import app as web_app

    monkeypatch.setattr(web_app, "build_nba_points_market", lambda *args, **kwargs: {
        "status": "unavailable", "line": args[1], "reason": "No exact offer.", "ev": None,
    })
    response = TestClient(web_app.app).get("/api/players/Research%20Guard/points-market?line=19.5&platform=PrizePicks")

    assert response.status_code == 200
    assert response.json() == {"status": "unavailable", "line": 19.5, "reason": "No exact offer.", "ev": None}
