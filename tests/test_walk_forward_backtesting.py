from datetime import datetime, timedelta, timezone

from analytics.backtesting import _walk_forward_validation


def test_walk_forward_excludes_results_that_were_not_known_yet():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entries = []
    for index in range(22):
        placed = start + timedelta(days=index)
        settled = placed + timedelta(days=1)
        if index == 0:
            settled = start + timedelta(days=60)
        entries.append({
            "id": index + 1,
            "status": "Settled",
            "result": "Win" if index % 2 == 0 else "Loss",
            "placed_at": placed,
            "settled_at": settled,
            "props": [{"confidence": 60.0, "sport": "WNBA"}],
        })

    result = _walk_forward_validation(entries)
    first_prediction = next(row for row in result["predictions"] if row["entry_id"] == 12)

    assert result["leakage_free"] is True
    assert first_prediction["train_count"] == 10

