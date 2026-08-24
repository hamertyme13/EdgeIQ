from datetime import UTC, datetime
from types import SimpleNamespace

from data.providers import pandascore


def test_market_support_requires_key_and_documented_stat(monkeypatch):
    monkeypatch.delenv("PANDASCORE_API_KEY", raising=False)
    support = pandascore.market_support("CS2", "Maps 1-2 Kills")
    assert support["eligible"] is False
    assert "not configured" in support["reasons"][-1]

    monkeypatch.setenv("PANDASCORE_API_KEY", "test-token")
    assert pandascore.market_support("CS2", "Maps 1-2 Kills")["eligible"] is True
    assert pandascore.market_support("CS2", "Fantasy Score")["eligible"] is False
    assert pandascore.market_support("COD", "Kills")["eligible"] is False


def test_map_scoped_market_uses_only_requested_maps():
    row = {
        "kills": 48,
        "games": [
            {"map_number": 1, "kills": 12, "deaths": 8},
            {"map_number": 2, "kills": 15, "deaths": 11},
            {"map_number": 3, "kills": 21, "deaths": 14},
        ],
    }
    assert pandascore._actual_for_market(row, "Maps 1-2 Kills") == 27
    assert pandascore._actual_for_market(row, "Map 2 Kills + Deaths") == 26
    assert pandascore._actual_for_market(row, "Maps 1-4 Kills") is None


def test_refresh_imports_exact_finished_match_player_stat(monkeypatch):
    monkeypatch.setenv("PANDASCORE_API_KEY", "test-token")
    match = {
        "id": 91,
        "status": "finished",
        "begin_at": "2026-08-23T18:00:00Z",
        "opponents": [
            {"opponent": {"name": "Team Alpha"}},
            {"opponent": {"name": "Team Beta"}},
        ],
    }
    stats = [{
        "player": {"id": 7, "name": "s1mple"},
        "team": {"name": "Team Alpha", "acronym": "ALP"},
        "games": [
            {"map_number": 1, "kills": 16},
            {"map_number": 2, "kills": 19},
            {"map_number": 3, "kills": 22},
        ],
    }]

    def fake_get_json(url, **_kwargs):
        return SimpleNamespace(data=stats if "/players/stats" in url else [match], stale=False)

    saved = []
    monkeypatch.setattr(pandascore, "get_json", fake_get_json)
    monkeypatch.setattr(
        pandascore.FinalStatsRepository,
        "upsert_many",
        lambda rows: saved.extend(rows) or len(rows),
    )
    entry = {
        "placed_at": datetime(2026, 8, 23, 12, tzinfo=UTC),
        "props": [{
            "player": "s1mple",
            "team": "Team Alpha",
            "sport": "CS2",
            "stat": "Maps 1-2 Kills",
            "game": "Team Alpha vs Team Beta",
            "game_time": "2026-08-23T18:00:00Z",
        }],
    }
    result = pandascore.refresh_final_stats_for_entries([entry], lookback_days=0)

    assert result["imported"] == 1
    assert result["matches_checked"] == 1
    assert saved[0]["actual"] == 35
    assert saved[0]["provider_player_id"] == "7"
    assert saved[0]["source"] == "pandascore_verified"


def test_stale_pandascore_payload_is_never_used_for_settlement(monkeypatch):
    monkeypatch.setenv("PANDASCORE_API_KEY", "test-token")
    monkeypatch.setattr(
        pandascore,
        "get_json",
        lambda *_args, **_kwargs: SimpleNamespace(data=[], stale=True),
    )
    try:
        pandascore._request("/csgo/matches/past", ttl_seconds=1)
    except RuntimeError as exc:
        assert "not used for settlement" in str(exc)
    else:
        raise AssertionError("stale evidence should fail closed")
