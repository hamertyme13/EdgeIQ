from analytics.model_version_evaluation import evaluate_model_versions


def _row(version: str, probability: float, result: str, key: str, current: float, trailing: float) -> dict:
    return {
        "model_version": version, "probability": probability, "result": result,
        "independent_market_key": key, "outcome_source": "espn", "legacy_quarantined": False,
        "feature_snapshot": {"features": {"history_filter_comparison": {
            "current_season": {"probability": current}, "trailing_history": {"probability": trailing},
        }}},
        "sport": "WNBA", "stat": "Points", "platform": "PrizePicks",
    }


def test_evaluation_tracks_brier_by_version_and_history_filter() -> None:
    rows = [
        _row("edgeiq-v2.3.0", 60, "Win", "old-1", 60, 55),
        _row("edgeiq-v2.3.0", 60, "Loss", "old-2", 60, 55),
        _row("edgeiq-v2.4.0", 70, "Win", "new-1", 70, 55),
        _row("edgeiq-v2.4.0", 70, "Win", "new-2", 70, 55),
    ]

    result = evaluate_model_versions(rows)

    assert len(result["versions"]) == 2
    assert result["v2_4_vs_v2_3"]["ready"] is True
    assert result["v2_4_vs_v2_3"]["brier_improvement"] > 0
    assert result["history_filter_comparison"]["samples"] == 4
    assert result["history_filter_comparison"]["preferred"] == "current-season"
    assert result["segments"][0]["sport"] == "WNBA"
    assert result["segments"][0]["maturity"] == "paper_only"
