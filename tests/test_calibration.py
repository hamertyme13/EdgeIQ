from analytics.calibration import calibrate


def test_calibration_bucket_uses_observed_mean_prediction() -> None:
    bucket = calibrate([
        {"win_probability": 50.1, "result": "Win"},
        {"win_probability": 50.3, "result": "Loss"},
    ])[0]

    assert round(bucket.predicted_mid, 1) == 50.2
    assert round(bucket.error, 1) == -0.2
