from services.odds import get_games


def test_get_games_uses_provider_cache(monkeypatch):
    expected = [{"away_team": "A", "home_team": "B", "bookmakers": []}]

    class _Response:
        data = expected

    monkeypatch.setattr("services.odds.get_json", lambda *args, **kwargs: _Response())

    assert get_games() == expected
