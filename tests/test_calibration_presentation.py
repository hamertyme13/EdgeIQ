from analytics.calibration_presentation import calibration_presentation


def _result(**overrides):
    return {
        "tier": "sport_stat_provider_direction_source",
        "sample_size": 150,
        "segment_sample_size": 150,
        "raw_probability": 72.0,
        "probability": 69.0,
        "uncertainty_points": 7.0,
        **overrides,
    }


def test_calibration_presentation_has_evidence_and_never_invents_error():
    result = calibration_presentation(_result())
    assert result["status"] == "CALIBRATED"
    assert result["model_probability"] == 72.0
    assert result["calibrated_probability"] == 69.0
    assert result["sample_size"] == 150
    assert result["calibration_error"] is None
    assert result["brier_score"] is None


def test_small_segment_and_hierarchical_fallback_are_labeled_partial():
    narrow = calibration_presentation(_result(sample_size=35, segment_sample_size=35))
    fallback = calibration_presentation(_result(tier="sport", sample_size=200, segment_sample_size=8))
    assert narrow["status"] == "PARTIAL"
    assert fallback["status"] == "PARTIAL"
    assert fallback["basis"] == "sport-wide fallback"


def test_missing_weak_and_uncalibrated_evidence_are_not_called_validated():
    assert calibration_presentation(None)["status"] == "UNAVAILABLE"
    assert calibration_presentation(_result(uncertainty_points=15.0))["status"] == "DEGRADED"
    capped = calibration_presentation(_result(tier="uncalibrated", sample_size=0, probability=65.0))
    assert capped["status"] == "INSUFFICIENT_SAMPLE"
    assert capped["calibrated_probability"] is None
    assert capped["display_probability"] == 65.0
