from web.application.prop_win_history import summarize_prop_results


def test_winning_leg_survives_losing_entry_and_duplicates():
    row = dict(stat="Points", direction="Over", line=19.5, provider_event_id="game1",
               actual=24, final_status="played", final_source="espn", final_result="Win", entry_result="Loss")
    results = summarize_prop_results([row, dict(row), dict(row, provider_event_id="game2", final_result="Loss", actual=10)], "Points")
    assert results[0]["wins"] == 1
    assert results[0]["losses"] == 1


def test_unverified_and_other_stats_are_excluded():
    row = dict(stat="Points", direction="Under", line=19.5, provider_event_id="game1",
               actual=10, final_status="played", final_source="projection_estimate", final_result="Win")
    assert summarize_prop_results([row], "Points") == []
    assert summarize_prop_results([dict(row, final_source="espn")], "Rebounds") == []


def test_conflicts_bad_results_and_missing_game_are_withheld():
    row = dict(stat="Points", direction="Over", line=19.5, provider_event_id="game1",
               actual=24, final_status="played", final_source="espn", final_result="Win")
    assert summarize_prop_results([row, dict(row, actual=10, final_result="Loss")], "Points") == []
    assert summarize_prop_results([dict(row, actual=10)], "Points") == []
    assert summarize_prop_results([dict(row, actual=float("nan"))], "Points") == []
    assert summarize_prop_results([dict(row, provider_event_id="", game_time="2026-09-15")], "Points") == []


def test_exact_line_record_is_separate_from_other_lines():
    row = dict(stat="Points", direction="Over", line=19.5, provider_event_id="game1",
               actual=24, final_status="played", final_source="espn", final_result="Win")
    result = summarize_prop_results([row, dict(row, line=25.5, final_result="Loss")], "Points", 19.5)[0]
    assert result["wins"] == 1 and result["losses"] == 1
    assert result["exact_line_wins"] == 1 and result["exact_line_losses"] == 0


def test_cross_book_same_game_is_counted_once_and_push_is_not_a_win():
    row = dict(stat="Points", direction="Over", line=19.5, provider_event_id="pp-game",
               game="IND @ MIN", game_time="2026-09-15T19:00:00Z",
               actual=24, final_status="played", final_source="espn", final_result="Win")
    result = summarize_prop_results([row, dict(row, provider_event_id="ud-game", game="MIN @ IND")], "Points")
    assert result[0]["wins"] == 1
    assert summarize_prop_results([dict(row, actual=19.5)], "Points") == []
