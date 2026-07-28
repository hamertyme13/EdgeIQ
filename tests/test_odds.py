from services.betting import implied_probability
from services.odds import find_game_odds, format_consensus_line, get_games

def test_positive_odds():
    assert round(implied_probability(150), 3) == 0.400

def test_negative_odds():
    assert round(implied_probability(-110), 3) == 0.524


def test_odds_api_uses_redacted_cache_key(monkeypatch):
    observed = {}

    class Response:
        data = []

    def fake_get_json(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return Response()

    monkeypatch.setenv("ODDS_API_KEY", "secret-value")
    monkeypatch.setattr("services.odds.get_json", fake_get_json)

    assert get_games("WNBA") == []
    assert "secret-value" in observed["url"]
    assert "secret-value" not in observed["cache_key"]
    assert "basketball_wnba" in observed["url"]


def test_find_game_odds_matches_abbreviated_matchup_and_formats_consensus():
    games = [{
        "id": "game-1",
        "away_team": "New York Yankees",
        "home_team": "Detroit Tigers",
        "bookmakers": [
            {"markets": [{"key": "h2h", "outcomes": [
                {"name": "New York Yankees", "price": 120},
                {"name": "Detroit Tigers", "price": -135},
            ]}]},
            {"markets": [{"key": "h2h", "outcomes": [
                {"name": "New York Yankees", "price": 110},
                {"name": "Detroit Tigers", "price": -130},
            ]}]},
        ],
    }]

    odds = find_game_odds("NYY @ DET", "MLB", games)

    assert odds is not None
    assert odds["sportsbook_count"] == 2
    assert odds["consensus"]["New York Yankees"] == 115
    assert "+115" in format_consensus_line(odds)
    assert "-132" in format_consensus_line(odds)
