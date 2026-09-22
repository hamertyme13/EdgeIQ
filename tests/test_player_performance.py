from web.application.player_performance import performance_summary


def prediction(**changes):
    return dict({"player_identity_id": 1, "independent_market_key": "market1", "model_version": "v2.4",
                 "outcome_source": "espn", "predicted_at": "2026-09-10T10:00:00Z",
                 "feature_as_of": "2026-09-10T09:00:00Z", "game_time": "2026-09-10T18:00:00Z",
                 "settled_at": "2026-09-10T22:00:00Z", "probability": 60, "actual": 22,
                 "line": 20.5, "direction": "Over", "result": "Win", "platform": "PrizePicks"}, **changes)


def test_uses_first_independent_forecast_and_preserves_versions():
    rows = [prediction(), prediction(probability=99, predicted_at="2026-09-10T11:00:00Z"), prediction(model_version="v2.3")]
    result = performance_summary(rows)
    assert len(result["versions"]) == 2
    for row in result["versions"]:
        assert row["settled_predictions"] == 1
        assert row["predicted_hit_rate"] == 60
        assert row["brier_score"] == .16
        assert row["small_sample"] is True
        assert "promotion_eligible" not in row
    assert result["roi"] is None


def test_excludes_legacy_anonymous_unverified_future_and_inconsistent_results():
    rows = [prediction(legacy_quarantined=True), prediction(player_identity_id=None),
            prediction(outcome_source="projection_estimate"), prediction(model_version="legacy"),
            prediction(feature_as_of="2026-09-11T00:00:00Z"), prediction(predicted_at="2026-09-10T19:00:00Z"),
            prediction(actual=10), prediction(probability=float("nan")), prediction(settled_at=None)]
    assert performance_summary(rows)["versions"] == []


def test_under_outcome_and_provider_segments():
    result = performance_summary([prediction(direction="Under", actual=10), prediction(platform="Underdog")])
    assert len(result["versions"]) == 2


def test_recent_form_under_is_not_over_rate():
    from web.app import _history_split
    rows = [{"actual": 10}, {"actual": 15}, {"actual": 30}]
    assert _history_split(rows, 20.5, "Under")["hit_rate"] == 66.7
    assert _history_split(rows, 20.5, "Over")["hit_rate"] == 33.3
