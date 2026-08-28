from data.providers import draftkings_pick6


def test_normalize_draftkings_pick6_offer():
    row = draftkings_pick6.normalize_offer({
        "id": "offer-1",
        "playerName": "Nikola Jokic",
        "playerId": "player-7",
        "league": "NBA",
        "team": "DEN",
        "statType": "Assists",
        "line": 8.5,
        "matchup": "DEN @ LAL",
        "startTime": "2026-08-25T23:00:00Z",
    })

    assert row is not None
    assert row["platform"] == "DraftKings Pick6"
    assert row["player_id"] == "player-7"
    assert row["line"] == 8.5
    assert row["line_offer_type"] == "standard"


def test_normalize_draftkings_pick6_rejects_incomplete_offer():
    assert draftkings_pick6.normalize_offer({"playerName": "Missing Market"}) is None


def test_draftkings_pick6_uses_fresh_cache_without_actor_run(monkeypatch):
    monkeypatch.setattr(draftkings_pick6, "_read_cache", lambda: (30, [{"player": "Cached"}]))
    monkeypatch.setattr(draftkings_pick6, "_token", lambda: "configured")
    monkeypatch.setattr(
        draftkings_pick6.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("actor should not run")),
    )

    assert draftkings_pick6.fetch_projections(refresh=True) == [{"player": "Cached"}]
