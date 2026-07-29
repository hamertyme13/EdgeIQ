from services.betting import implied_probability
from services.odds import (
    find_game_odds,
    format_consensus_line,
    get_games,
    get_player_prop_consensus,
    prop_market_key,
    summarize_player_prop_market,
)

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


def test_player_prop_market_mapping_normalizes_pra_and_mlb_stats():
    assert prop_market_key("PRA") == "player_points_rebounds_assists"
    assert prop_market_key("Points + Rebounds + Assists") == "player_points_rebounds_assists"
    assert prop_market_key("Hits + Runs + RBIs") == "batter_hits_runs_rbis"


def test_player_prop_consensus_uses_exact_paired_sportsbook_lines_only():
    event = {
        "id": "event-1",
        "away_team": "Indiana Fever",
        "home_team": "Seattle Storm",
        "commence_time": "2026-07-30T00:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [{
                    "key": "player_points_rebounds_assists",
                    "last_update": "2026-07-29T18:00:00Z",
                    "outcomes": [
                        {"name": "Over", "description": "Kelsey Mitchell", "price": -115, "point": 24.5},
                        {"name": "Under", "description": "Kelsey Mitchell", "price": -105, "point": 24.5},
                    ],
                }],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [{
                    "key": "player_points_rebounds_assists",
                    "outcomes": [
                        {"name": "Over", "description": "Kelsey Mitchell", "price": -110, "point": 24.5},
                        {"name": "Under", "description": "Kelsey Mitchell", "price": -110, "point": 24.5},
                        {"name": "Over", "description": "Kelsey Mitchell", "price": 120, "point": 25.5},
                        {"name": "Under", "description": "Kelsey Mitchell", "price": -150, "point": 25.5},
                    ],
                }],
            },
            {
                "key": "betmgm",
                "title": "BetMGM",
                "markets": [{
                    "key": "player_points_rebounds_assists",
                    "outcomes": [
                        {"name": "Over", "description": "Kelsey Mitchell", "price": -120, "point": 24.5},
                    ],
                }],
            },
            {
                "key": "prizepicks",
                "title": "PrizePicks",
                "markets": [{
                    "key": "player_points_rebounds_assists",
                    "outcomes": [
                        {"name": "Over", "description": "Kelsey Mitchell", "price": -137, "point": 24.5, "multiplier": 0.85},
                        {"name": "Under", "description": "Kelsey Mitchell", "price": -137, "point": 24.5, "multiplier": 1.0},
                    ],
                }],
            },
        ],
    }

    body = summarize_player_prop_market(
        event,
        player="Kelsey Mitchell",
        stat="PRA",
        line=24.5,
        direction="Over",
    )

    assert body["available"] is True
    assert body["book_count"] == 2
    assert 50 < body["market_probability"] < 52
    assert body["best_over_odds"] == -110
    assert len(body["dfs_offers"]) == 1
    assert body["dfs_offers"][0]["over"]["multiplier"] == 0.85
    assert all(row["bookmaker"] != "PrizePicks" for row in body["books"])


def test_player_prop_request_is_event_scoped_and_redacts_api_key(monkeypatch):
    observed = {}

    class Response:
        data = {
            "id": "event-1",
            "away_team": "Indiana Fever",
            "home_team": "Seattle Storm",
            "bookmakers": [],
        }
        stale = False
        age_seconds = 0

    def fake_get_json(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return Response()

    monkeypatch.setenv("ODDS_API_KEY", "secret-value")
    monkeypatch.setattr(
        "services.odds.get_events",
        lambda sport: [{
            "id": "event-1",
            "away_team": "Indiana Fever",
            "home_team": "Seattle Storm",
        }],
    )
    monkeypatch.setattr("services.odds.get_json", fake_get_json)

    body = get_player_prop_consensus(
        "Kelsey Mitchell",
        "PRA",
        "WNBA",
        "SEA",
        24.5,
        "Over",
        "IND",
    )

    assert body["configured"] is True
    assert "events/event-1/odds" in observed["url"]
    assert "includeMultipliers=true" in observed["url"]
    assert "secret-value" in observed["url"]
    assert "secret-value" not in observed["cache_key"]
