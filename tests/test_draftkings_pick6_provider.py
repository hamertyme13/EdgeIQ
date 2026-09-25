from data.providers import draftkings_pick6


def test_pick6_cached_evidence_ages_without_billable_refresh(tmp_path, monkeypatch):
    import json

    path = tmp_path / "pick6.json"
    path.write_text(json.dumps({"saved_at": 1000, "rows": [{"player": "Cached"}]}))
    monkeypatch.setattr(draftkings_pick6, "CACHE_PATH", path)
    monkeypatch.setattr(draftkings_pick6.time, "time", lambda: 1100)
    fresh = draftkings_pick6.fetch_projections()[0]
    monkeypatch.setattr(draftkings_pick6.time, "time", lambda: 5000)
    monkeypatch.setattr(draftkings_pick6.requests, "post", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No paid run")))
    stale = draftkings_pick6.fetch_projections()[0]
    assert not fresh["stale"]
    assert stale["stale"]
    assert stale["cache_age_seconds"] == 4000
    assert fresh["provider_offer_observed_at"] == stale["provider_offer_observed_at"]
    assert "provider_offer_verified_at" not in stale


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


def test_normalize_draftkings_pick6_keeps_nested_event_identity():
    row = draftkings_pick6.normalize_offer({
        "id": "offer-2",
        "playerName": "A Player",
        "playerId": "player-8",
        "league": "MLB",
        "team": {"abbreviation": "SEA"},
        "statType": "Hits",
        "line": 1.5,
        "event": {
            "id": "game-9",
            "awayTeam": {"abbreviation": "ATH"},
            "homeTeam": {"abbreviation": "SEA"},
            "startTime": "2026-09-05T02:10:00Z",
        },
    })

    assert row is not None
    assert row["game"] == "ATH @ SEA"
    assert row["game_time"] == "2026-09-05T02:10:00Z"
    assert row["provider_event_id"] == "game-9"
    assert row["provider_offer_id"] == "offer-2"


def test_draftkings_pick6_uses_fresh_cache_without_actor_run(monkeypatch):
    monkeypatch.setattr(draftkings_pick6, "_read_cache", lambda: (30, [{"player": "Cached"}]))
    monkeypatch.setattr(draftkings_pick6, "_token", lambda: "configured")
    monkeypatch.setattr(
        draftkings_pick6.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("actor should not run")),
    )

    assert draftkings_pick6.fetch_projections(refresh=True) == [{"player": "Cached"}]
