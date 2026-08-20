from concurrent.futures import ThreadPoolExecutor

from repository.repositories.plausibility_rejection_repository import PlausibilityRejectionRepository
from utils.prop_plausibility import prop_line_plausibility


def test_rejection_preserves_provider_payload_and_normalized_diagnostics():
    payload = {
        "id": "offer-bad-line",
        "platform": "PrizePicks",
        "player": "Example Player",
        "sport": "WNBA",
        "stat": "Points",
        "line": "155.5",
        "provider_only_field": {"contract": "untouched"},
    }
    result = prop_line_plausibility(payload)

    stored = PlausibilityRejectionRepository.record(payload, result)

    assert stored["rejection_reason"] == result.reason
    assert stored["original_provider_payload"] == payload
    assert stored["provider"] == "PrizePicks"
    assert stored["timestamp"]
    assert stored["normalized_value"] == "155.5"
    assert stored["expected_range"] == {"minimum": 0.5, "maximum": 55.5}


def test_concurrent_duplicate_rejections_coalesce_without_losing_occurrences():
    payload = {
        "id": "concurrent-bad-line",
        "platform": "Underdog",
        "player": "Example Player",
        "sport": "NFL",
        "stat": "Passing Yards",
        "line": 999.5,
    }
    result = prop_line_plausibility(payload)

    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(executor.map(lambda _: PlausibilityRejectionRepository.record(payload, result), range(8)))

    latest = PlausibilityRejectionRepository.recent(limit=100)
    matching = [row for row in latest if row["original_provider_payload"].get("id") == "concurrent-bad-line"]
    assert len({row["id"] for row in rows}) == 1
    assert len(matching) == 1
    assert matching[0]["occurrence_count"] == 8


def test_batch_rejections_preserve_input_order_and_aggregate_duplicates():
    payload = {
        "id": "batch-bad-line",
        "platform": "PrizePicks",
        "player": "Batch Player",
        "sport": "NHL",
        "stat": "Goals",
        "line": 40.5,
    }
    result = prop_line_plausibility(payload)

    rows = PlausibilityRejectionRepository.record_many([
        (payload, result, "PrizePicks"),
        (payload, result, "PrizePicks"),
    ])

    assert len(rows) == 2
    assert rows[0]["id"] == rows[1]["id"]
    assert rows[0]["occurrence_count"] == 2
