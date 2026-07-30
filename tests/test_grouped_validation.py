from datetime import UTC, datetime, timedelta, timezone

from analytics.grouped_validation import grouped_rolling_validation


def test_grouped_rolling_validation_uses_only_prior_settled_unique_markets() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(180):
        predicted = start + timedelta(days=index)
        rows.append({
            "independent_market_key": f"market-{index}",
            "sport": "WNBA",
            "stat": "Points",
            "direction": "Over",
            "probability": 80.0,
            "result": "Win" if index % 5 else "Loss",
            "predicted_at": predicted.isoformat(),
            "settled_at": (predicted + timedelta(hours=4)).isoformat(),
            "game": f"game-{index}",
            "legacy_quarantined": False,
        })

    result = grouped_rolling_validation(rows)

    assert result["ready"] is True
    assert result["passed"] is True
    assert result["unique_predictions"] == 180
    assert result["evaluated_predictions"] >= 30
    assert result["leakage_free"] is True
