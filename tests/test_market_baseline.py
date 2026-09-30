from datetime import UTC, datetime, timedelta

from services.market_baseline import capture_market_baseline


def _row(**market_changes):
    captured = datetime(2026, 9, 28, 15, tzinfo=UTC)
    start = captured + timedelta(hours=2)
    market = {
        "available": True, "source_type": "multi_book_no_vig", "stale": False,
        "book_count": 3, "timestamped_book_count": 3,
        "market_probability": 56.2, "line": 20.5,
        "direction": "Over", "oldest_update": (captured - timedelta(minutes=5)).isoformat(),
        "last_update": (captured - timedelta(minutes=3)).isoformat(),
        "event": {"event_id": "event-1", "commence_time": start.isoformat()},
        **market_changes,
    }
    return {"player": "Player One", "line": 20.5, "direction": "Over",
            "game_time": start.isoformat(), "decision_receipt": {"market_consensus": market}}, captured


def test_exact_pregame_multi_book_odds_are_frozen():
    row, captured = _row()
    baseline, reason = capture_market_baseline(row, captured)
    assert reason == ""
    assert baseline["probability"] == 56.2
    assert baseline["book_count"] == 3


def test_stale_single_book_wrong_line_and_postgame_odds_are_excluded():
    for changes in (
        {"stale": True}, {"book_count": 1}, {"line": 21.5},
        {"oldest_update": "2026-09-28T12:00:00Z"},
        {"direction": "Under"}, {"event": {"event_id": "other", "commence_time": "2026-09-29T01:00:00Z"}},
        {"book_count": "not-a-number"},
        {"timestamped_book_count": 2},
        {"last_update": (datetime(2026, 9, 28, 15, tzinfo=UTC) + timedelta(minutes=1)).isoformat()},
        {"last_update": "not-a-time"},
    ):
        row, captured = _row(**changes)
        baseline, reason = capture_market_baseline(row, captured)
        assert baseline is None
        assert reason
