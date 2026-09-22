from web.application.model_track_record import summarize_track_record


def row(**changes):
    return {"player_identity_id":1, "independent_market_key":"m1", "model_version":"v2.4",
            "predicted_at":"2026-09-01T10:00:00Z", "game_time":"2026-09-01T18:00:00Z",
            "feature_as_of":"2026-09-01T09:00:00Z", "settled_at":"2026-09-01T22:00:00Z",
            "probability":60, "actual":22, "line":20.5, "direction":"Over", "platform":"PrizePicks",
            "result":"Win", "outcome_source":"espn", **changes}


def test_locked_settled_push_and_pending_counts_are_distinct():
    result = summarize_track_record([row(), row(), row(independent_market_key="m2", result="", actual=None, settled_at=None),
                                    row(independent_market_key="m3", result="Push", actual=20.5)])
    assert result["locked_predictions"] == 3
    assert result["settled_predictions"] == 2
    assert result["wins"] == 1 and result["pushes"] == 1
    assert result["unresolved_or_excluded"] == 1
    assert result["roi"] is None and result["clv"] is None and result["score_buckets"] is None


def test_legacy_future_and_anonymous_are_not_locked_evidence():
    result = summarize_track_record([row(legacy_quarantined=True), row(player_identity_id=None),
                                    row(predicted_at="2026-09-01T19:00:00Z")])
    assert result["locked_predictions"] == 0


def test_chronological_first_prediction_and_versions_are_preserved():
    result = summarize_track_record([row(probability=99, predicted_at="2026-09-01T11:00:00Z"), row(), row(model_version="v2.3")])
    assert result["locked_predictions"] == 2
    assert all(item["predicted_hit_rate"] == 60 for item in result["versions"])
    assert all(item["small_sample"] for item in result["versions"])
