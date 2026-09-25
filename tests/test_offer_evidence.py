import json
from datetime import UTC, datetime

from web.application.offer_evidence import handoff_blocking_reason, offer_freshness, same_offer_game


def test_handoff_reasons_distinguish_required_actions():
    assert 'reanalyze' in handoff_blocking_reason('changed', 15, True, 'fresh')
    assert 'matchup' in handoff_blocking_reason('unavailable', 15, False, 'unknown')
    assert 'offer ID' in handoff_blocking_reason('current', 15, False, 'fresh')
    assert 'Refresh offers' in handoff_blocking_reason('current', 15, True, 'expired')
    assert 'Reanalysis alone cannot' in handoff_blocking_reason('current', 15, True, 'unknown')
    assert handoff_blocking_reason('current', 15, True, 'fresh') == ''
    assert offer_freshness({'stale': True, 'provider_offer_verified_at': datetime.now(UTC).isoformat()}) == 'expired'


def test_offer_game_identity_requires_exact_event_or_dated_matchup():
    request = {"game": "A vs B", "game_time": "2026-09-23T20:00:00Z"}
    assert same_offer_game(request, {**request, "game_time": "2026-09-23T16:00:00-04:00"})
    assert not same_offer_game(request, {**request, "game_time": "2026-09-24T20:00:00Z"})
    assert not same_offer_game(request, {"game": "A vs B"})
    assert not same_offer_game({}, {})
    assert not same_offer_game(request, {**request, "game_time": "2026-09-23T20:00:00"})
    assert same_offer_game({"provider_event_id": "123"}, {"game_id": "123"})
    assert not same_offer_game({**request, "provider_event_id": "123"}, {**request, "event_id": "456"})
    assert not same_offer_game({**request, "provider_event_id": "123"},
                               {**request, "event_id": "123", "game_time": "2026-09-24T20:00:00Z"})


def test_cached_offer_keeps_original_verification_time(tmp_path, monkeypatch):
    from data.providers import cache

    path = tmp_path / "response.json"
    path.write_text(json.dumps({"saved_at": 1000, "data": []}))
    monkeypatch.setattr(cache.time, "time", lambda: 1200)
    first = cache._read_cache(path)
    monkeypatch.setattr(cache.time, "time", lambda: 1600)
    second = cache._read_cache(path)
    assert first.verified_at == second.verified_at
    assert second.age_seconds == 600


def test_model_timestamp_cannot_verify_provider_offer():
    now = datetime(2026, 9, 22, 12, tzinfo=UTC)
    assert offer_freshness({"feature_as_of": now.isoformat()}, now=now) == "unknown"
    for value in ["invalid", "2026-09-22T12:00:00", "2026-09-22T12:01:00Z"]:
        assert offer_freshness({"provider_offer_verified_at": value}, now=now) == "unknown"
    assert offer_freshness({"provider_offer_verified_at": "2026-09-22T11:55:00Z"}, now=now) == "fresh"
    assert offer_freshness({"provider_offer_verified_at": "2026-09-22T11:54:59Z"}, now=now) == "expired"
