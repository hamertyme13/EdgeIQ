from analytics.wilson_interval import wilson_interval_95


def test_wilson_interval_handles_small_and_large_observed_samples():
    assert wilson_interval_95(0, 0) is None
    assert wilson_interval_95(2, 1) is None
    assert wilson_interval_95(1, 1) == [20.7, 100.0]
    assert wilson_interval_95(50, 100) == [40.4, 59.6]
