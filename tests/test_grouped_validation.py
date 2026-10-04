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


def test_grouped_validation_matches_prior_settled_segment_calibration() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(60):
        predicted = start + timedelta(days=index)
        rows.append({
            "independent_market_key": f"market-{index}",
            "sport": "WNBA" if index % 3 else "MLB",
            "stat": "Points" if index % 2 else "Assists",
            "direction": "Over" if index % 4 else "Under",
            "probability": 70.0,
            "result": "Win" if index % 5 else "Loss",
            "predicted_at": predicted.isoformat(),
            "settled_at": (predicted + timedelta(hours=4)).isoformat(),
            "legacy_quarantined": False,
        })

    expected = []
    for target in rows:
        train = [row for row in rows if row["settled_at"] < target["predicted_at"]]
        if len(train) < 5:
            continue
        peers = [row for row in train if all(row[key].lower() == target[key].lower() for key in ("sport", "stat", "direction"))]
        if len(peers) < 20:
            peers = [row for row in train if row["sport"] == target["sport"]]
        probability = (0.7 * 30 + sum(row["result"] == "Win" for row in peers)) / (30 + len(peers))
        actual = float(target["result"] == "Win")
        expected.append((probability - actual) ** 2)

    result = grouped_rolling_validation(rows, minimum_train=5, minimum_predictions=1)
    assert result["evaluated_predictions"] == len(expected)
    assert result["brier_score"] == round(sum(expected) / len(expected), 4)
