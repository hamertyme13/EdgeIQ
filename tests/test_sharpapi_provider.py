from datetime import UTC, datetime, timedelta

from data.providers import sharpapi


def _row(**changes):
    row = {
        "id": "offer-1",
        "sportsbook": "underdog",
        "event_id": "game-1",
        "league": "wnba",
        "market_type": "player_points",
        "player_name": "A'ja Wilson",
        "selection": "Over",
        "selection_type": "over",
        "line": 22.5,
        "is_main_line": True,
        "is_active": True,
        "is_live": False,
        "event_start_time": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
        "home_team": "Las Vegas Aces",
        "away_team": "Indiana Fever",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    row.update(changes)
    return row


def test_normalization_keeps_player_side_and_third_party_provenance():
    prop = sharpapi.normalize_player_prop(_row())
    assert prop is not None
    assert prop["player"] == "A'ja Wilson"
    assert prop["direction"] == "Over"
    assert prop["platform"] == "Underdog"
    assert prop["provider_source"] == "SharpAPI (third-party)"
    assert prop["payout_evidence"] == "unverified"


def test_rejects_live_alternate_suspended_and_non_player_markets():
    for change in (
        {"is_live": True}, {"is_main_line": False}, {"is_active": False},
        {"market_type": "moneyline"}, {"market_segment": "1st_half"},
        {"selection_type": "yes"}, {"event_start_time": ""},
    ):
        assert sharpapi.normalize_player_prop(_row(**change)) is None


def test_no_key_means_no_request(monkeypatch):
    monkeypatch.delenv("SHARPAPI_API_KEY", raising=False)
    assert sharpapi.fetch_player_props() == []


def test_pagination_deduplicates_and_stops(monkeypatch):
    monkeypatch.setenv("SHARPAPI_API_KEY", "test-key")
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        assert kwargs["headers"]["X-API-Key"] == "test-key"
        page = len(calls)
        return type("Response", (), {
            "stale": False,
            "data": {
                "data": [_row()],
                "pagination": {"has_more": page == 1, "next_cursor": "second" if page == 1 else None},
            },
        })()

    monkeypatch.setattr(sharpapi, "get_json", fake_get)
    assert len(sharpapi.fetch_player_props()) == 1
    assert len(calls) == 2
    assert "cursor=second" in calls[1]


def test_underdog_stale_direct_board_uses_fallback(monkeypatch):
    from web import app

    monkeypatch.setattr(app.underdog, "fetch_projections", lambda: [{"stale": True, "player": "Old"}])
    monkeypatch.setattr(app.sharpapi, "fetch_player_props", lambda book: [{"player": "Fresh", "stale": False}])
    assert app._fetch_underdog_platform_props()[0]["player"] == "Fresh"


def test_underdog_fallback_failure_does_not_serve_stale_offers(monkeypatch):
    from web import app

    monkeypatch.setattr(app.underdog, "fetch_projections", lambda: [{"stale": True, "player": "Old"}])

    def denied(_book):
        raise RuntimeError("tier restricted")

    monkeypatch.setattr(app.sharpapi, "fetch_player_props", denied)
    monkeypatch.setattr(app.underdog_apify, "fetch_projections", lambda _sport=None: [])
    assert app._fetch_underdog_platform_props() == []


def test_underdog_actor_fallback_after_sharpapi_rejection(monkeypatch):
    from web import app

    monkeypatch.setattr(app.underdog, "fetch_projections", lambda: [{"stale": True}])
    monkeypatch.setattr(app.sharpapi, "fetch_player_props", lambda _book: [])
    monkeypatch.setattr(app.underdog_apify, "fetch_projections", lambda _sport=None: [{"player": "Actor"}])
    assert app._fetch_underdog_platform_props() == [{"player": "Actor"}]


def test_selected_underdog_sport_reaches_actor_fetch_boundary(monkeypatch):
    from web import app

    monkeypatch.setattr(app.underdog_apify, "configured", lambda: True)
    monkeypatch.setattr(app.sleeper_apify, "configured", lambda: True)
    calls = []

    def fetch(platform, **kwargs):
        calls.append((platform, kwargs))
        return []

    monkeypatch.setattr(app, "_fetch_platform_props", fetch)
    app._fetch_selected_platform_props("Underdog", "NFL")
    app._fetch_selected_platform_props("Sleeper", "NFL")
    assert calls == [
        ("Underdog", {"sport_filter": "NFL"}),
        ("Sleeper", {"sport_filter": "NFL"}),
    ]
