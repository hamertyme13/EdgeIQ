from analytics.release_validation import validation_readiness


def _entry(index: int, *, paper: bool = True) -> dict:
    return {
        "status": "Settled",
        "result": "Win" if index % 2 == 0 else "Loss",
        "entry_mode": "paper" if paper else "real",
        "props": [
            {
                "player": f"Player {index}-{leg}",
                "sport": "WNBA",
                "stat": "Points",
                "line": 10.5 + leg,
                "direction": "Over",
                "game": f"A{index}@B{index}",
                "final_result": "Win",
                "final_source": "espn",
            }
            for leg in range(3)
        ],
    }


def test_validation_readiness_passes_complete_evidence() -> None:
    segments = [
        {"type": "Confidence"},
        {"type": "Grade"},
        {"type": "Sport"},
        {"type": "Stat"},
        {"type": "Platform"},
    ]
    result = validation_readiness(
        [_entry(index) for index in range(100)],
        segments,
        {"total": 300, "average_abs_error": 8.5},
        {"ready": True, "passed": True},
        {"ready": True, "passed": True},
        {"tracked_legs": 50},
        prediction_rows=[
            {
                "independent_market_key": f"market-{index}",
                "result": "Win",
                "outcome_source": "espn",
                "legacy_quarantined": False,
            }
            for index in range(500)
        ],
        grouped_validation={"ready": True, "passed": True, "message": "Passed."},
    )

    assert result["status"] == "validated"
    assert result["passed_gates"] == result["total_gates"]
    assert result["counts"]["settled_paper_entries"] == 100
    assert result["counts"]["settled_props"] == 500


def test_validation_readiness_excludes_unverified_props() -> None:
    entry = _entry(1)
    entry["props"][0]["final_source"] = "projection_estimate"

    result = validation_readiness(
        [entry],
        [],
        {"total": 0, "average_abs_error": 0},
        {},
        {},
    )

    assert result["counts"]["settled_props"] == 2
    assert result["status"] == "collecting_evidence"


def test_validation_readiness_does_not_substitute_legacy_props_for_empty_ledger() -> None:
    result = validation_readiness(
        [_entry(1)],
        [],
        {"total": 0, "average_abs_error": 0},
        {},
        {},
        prediction_rows=[],
    )

    assert result["counts"]["raw_settled_props"] == 3
    assert result["counts"]["versioned_prediction_rows"] == 0
    assert result["counts"]["settled_props"] == 0
