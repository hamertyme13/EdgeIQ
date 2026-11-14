from analytics.observed_stat_range import locked_observed_range, observed_range_audit


def _snapshot(stat, samples=12):
    return {
        "stat": stat,
        "source": "verified_history_distribution",
        "sample_size": samples,
        "distribution": {"floor": 2, "percentile_25": 4, "percentile_75": 8, "ceiling": 12},
    }


def test_observed_range_is_reusable_for_rebounds_and_assists():
    for stat in ("Rebounds", "Assists"):
        assert locked_observed_range(_snapshot(stat)) == (2.0, 4.0, 8.0, 12.0)


def test_observed_range_requires_verified_ordered_history():
    assert locked_observed_range(_snapshot("Rebounds", samples=4)) is None
    snapshot = _snapshot("Assists")
    snapshot["source"] = "market_prior"
    assert locked_observed_range(snapshot) is None
    snapshot = _snapshot("Assists")
    snapshot["distribution"]["ceiling"] = 3
    assert locked_observed_range(snapshot) is None


def test_range_audit_excludes_unavailable_finals():
    bounds = locked_observed_range(_snapshot("Assists"))
    audit = observed_range_audit([
        {"observed_range": bounds, "actual": 6},
        {"observed_range": bounds, "actual": 11},
        {"observed_range": bounds, "actual": float("nan")},
        {"observed_range": None, "actual": 5},
    ])
    assert audit["status"] == "descriptive_only"
    assert audit["samples"] == 2
    assert audit["middle_half_coverage"] == 50.0
    assert audit["wider_range_coverage"] == 100.0
