from web.application.personal_edge_service import summarize_personal_edge


def _row(entry_id=1, **changes):
    row = {
        "entry_id": entry_id, "entry_result": "Loss", "entry_size": 2,
        "grade": "B", "profit": -10, "settled_at": "2026-10-01T12:00:00",
        "sport": "WNBA", "stat": "Points", "platform": "PrizePicks",
        "direction": "Over", "confidence": 92, "line": 19.5, "actual": 22,
        "final_source": "espn", "final_status": "played", "final_result": "Win",
    }
    row.update(changes)
    return row


def test_winning_leg_counts_even_when_card_loses_and_paper_is_separate():
    rows = [_row(), _row(final_result="Loss", actual=12)]
    paid = summarize_personal_edge(rows, mode="real")
    paper = summarize_personal_edge([], mode="paper")
    assert paid["summary"]["settled_entries"] == 1
    assert paid["summary"]["leg_wins"] == 1
    assert paid["summary"]["leg_losses"] == 1
    assert paid["card_size"][0]["losses"] == 1
    assert paper["summary"]["verified_leg_decisions"] == 0


def test_unverified_conflicting_and_push_legs_are_excluded():
    rows = [
        _row(),
        _row(2, final_source="manual"),
        _row(3, final_result="Loss"),
        _row(4, actual=19.5, final_result="Push"),
        _row(5, final_status="scheduled"),
    ]
    result = summarize_personal_edge(rows, mode="real")
    assert result["summary"]["verified_leg_decisions"] == 1
    assert result["summary"]["excluded_legs"] == 4
    assert result["segments"]["confidence_bucket"][0]["name"] == "90-100%"


def test_rankings_require_30_decisions_and_complete_history():
    rows = [_row(i, entry_result="Win") for i in range(1, 31)]
    result = summarize_personal_edge(rows, mode="real")
    assert result["strongest"]["decisions"] == 30
    assert result["segments"]["sport"][0]["small_sample"] is False
    assert summarize_personal_edge(rows[:29], mode="real")["strongest"] is None
    assert summarize_personal_edge(rows, mode="real", truncated=True)["strongest"] is None
