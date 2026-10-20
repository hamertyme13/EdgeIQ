from datetime import UTC, datetime, timedelta

from web.application.model_input_status import model_input_status


def test_model_input_status_uses_player_feature_freshness_window():
    now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    current = model_input_status(
        {"segments": 42, "last_materialized_at": (now - timedelta(hours=11)).isoformat()}, now=now
    )
    stale = model_input_status(
        {"segments": 42, "last_materialized_at": (now - timedelta(hours=13)).isoformat()}, now=now
    )

    assert current["status"] == "ready"
    assert current["label"] == "Model Inputs"
    assert stale["status"] == "attention"
    assert stale["value"] == "Refresh needed"


def test_model_input_status_does_not_call_missing_or_invalid_timestamps_fresh():
    now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    assert model_input_status({"segments": 0}, now=now)["value"] == "No features yet"
    assert model_input_status({"segments": 3, "last_materialized_at": "invalid"}, now=now)["status"] == "attention"
    assert model_input_status(
        {"segments": 3, "last_materialized_at": (now + timedelta(minutes=2)).isoformat()}, now=now
    )["status"] == "attention"


def test_model_input_status_requires_coverage_for_all_cached_segments():
    now = datetime(2026, 10, 13, 12, tzinfo=UTC)
    status = model_input_status({
        "segments": 10,
        "current_segments": 1,
        "sourced_segments": 8,
        "last_materialized_at": now.isoformat(),
        "latest_source_game_date": "2026-10-12",
    }, now=now)
    assert status["status"] == "attention"
    assert status["value"] == "1/10 current"
    assert "8/10 have dated source games" in status["detail"]
