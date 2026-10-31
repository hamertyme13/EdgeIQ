from datetime import UTC, datetime, timedelta

from web.application import briefing_service
from web.application.opportunity_presentation import mark_expired_briefing_for_refresh


def test_briefing_cache_expires_at_eastern_midnight_even_when_ttl_remains(monkeypatch):
    now = datetime(2026, 10, 25, 4, 15, tzinfo=UTC)
    monkeypatch.setattr(briefing_service, "utc_now", lambda: now)
    cache = {
        "created_at": (now - timedelta(minutes=30)).isoformat(),
        "expires_at": (now + timedelta(hours=9)).isoformat(),
    }
    assert briefing_service.daily_briefing_cache_is_fresh(cache, 10) is False

    cache["created_at"] = (now - timedelta(minutes=10)).isoformat()
    assert briefing_service.daily_briefing_cache_is_fresh(cache, 10) is True


def test_all_expired_cached_props_request_refresh_without_hiding_the_board():
    payload = {"top_opportunities": [
        {"player": "One", "edgeiq_score_freshness": {"status": "expired"}},
        {"player": "Two", "edgeiq_score_freshness": {"status": "unknown"}},
    ], "cache": {"hit": True, "stale": False, "requires_refresh": False}}
    marked = mark_expired_briefing_for_refresh(payload)
    assert marked["cache"]["requires_refresh"] is True
    assert marked["cache"]["stale"] is True
    assert len(marked["top_opportunities"]) == 2

    payload["top_opportunities"][0]["edgeiq_score_freshness"]["status"] = "fresh"
    assert mark_expired_briefing_for_refresh(payload)["cache"]["requires_refresh"] is False
