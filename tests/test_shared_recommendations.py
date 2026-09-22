from datetime import UTC, datetime, timedelta

from web.application.shared_recommendations import select_daily_snapshot, shared_opportunity_feed

NOW = datetime(2026, 9, 13, 16, tzinfo=UTC)


def feed():
    return {"daily_briefing": {"recommendation_snapshot_id": "s1", "as_of": NOW.isoformat(),
                               "platform": "PrizePicks", "requested_platform": "Both", "sport": "WNBA",
                               "top_opportunities": [{"player": "A", "edgeiq_score": {"score": 50}}]}}


def test_shared_snapshot_preserves_scores_and_does_not_mutate_source():
    source = feed()
    result = select_daily_snapshot(source, "Both", "WNBA", now=NOW)
    assert result["available"]
    assert result["snapshot_id"] == "s1"
    result["briefing"]["top_opportunities"][0]["player"] = "Changed"
    assert source["daily_briefing"]["top_opportunities"][0]["player"] == "A"


def test_wrong_scope_expired_and_future_snapshots_are_not_reused():
    assert not select_daily_snapshot(feed(), "Underdog", "WNBA", now=NOW)["available"]
    assert not select_daily_snapshot(feed(), "Both", "NFL", now=NOW)["available"]
    assert not select_daily_snapshot(feed(), "Both", "WNBA", now=NOW + timedelta(minutes=31))["available"]
    assert not select_daily_snapshot(feed(), "Both", "WNBA", now=NOW - timedelta(seconds=1))["available"]


def test_eastern_midnight_expires_previous_day_even_within_thirty_minutes():
    source = feed()
    source["daily_briefing"]["as_of"] = "2026-09-13T03:55:00+00:00"
    assert not select_daily_snapshot(source, "Both", "WNBA", now=datetime(2026, 9, 13, 4, 5, tzinfo=UTC))["available"]


def test_shared_mode_never_starts_an_independent_recommendation_scan():
    from web.application.advantage_service import advantage_center_payload

    def forbidden(*args):
        raise AssertionError("Independent scan must not run")

    result = advantage_center_payload(
        "PrizePicks", "WNBA", command_center=forbidden, shared_feed=lambda: {},
        clv_report=lambda: {}, data_health=lambda: {}, personal_profile=lambda: {},
        watchlist_alerts=lambda: [], line_shop_summary=forbidden,
        sportsbook_integrations=lambda: {}, bankroll_strategy=lambda: {},
    )
    assert result["opportunity_feed"] == []
    assert not result["shared_feed"]["available"]
    assert "Refresh Today" in result["shared_feed"]["message"]


def test_shared_opportunity_ev_filter_requires_verified_finite_values():
    source = feed()
    source["daily_briefing"]["top_opportunities"] = [
        {"player": "Unverified", "expected_value": 99},
        {"player": "Verified", "expected_value": 4, "expected_value_verified": True},
        {"player": "Invalid", "expected_value": float("nan"), "expected_value_verified": True},
        {"player": "Negative", "expected_value": -5, "expected_value_verified": True},
    ]
    result = shared_opportunity_feed(source, "Both", "WNBA", 0, 10, -110, now=NOW)
    assert [row["player"] for row in result["opportunities"]] == ["Verified"]
    assert result["summary"]["unverified_ev"] == 2
    assert result["filters"]["requires_verified_ev"]
    assert not result["odds_applied"]


def test_default_shared_feed_keeps_order_limit_and_unknown_ev():
    source = feed()
    source["daily_briefing"]["top_opportunities"] = [{"player": "A"}, {"player": "B"}]
    result = shared_opportunity_feed(source, "Both", "WNBA", None, 1, 999, now=NOW)
    assert [row["player"] for row in result["opportunities"]] == ["A"]
    assert result["count"] == 1
    expired = shared_opportunity_feed(source, "Both", "WNBA", None, 10, -110, now=NOW + timedelta(hours=1))
    assert expired["opportunities"] == []
    assert not expired["available"]
