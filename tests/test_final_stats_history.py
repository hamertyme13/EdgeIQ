from repository.repositories.final_stats_repository import _deduplicate_history


def test_history_deduplicates_same_game_across_sources() -> None:
    rows = [
        {"game_date": "2026-08-20", "game": "IND @ MIN", "actual": 24, "source": "espn"},
        {"game_date": "2026-08-20", "game": "MIN vs IND", "actual": 24, "source": "entry_ledger"},
        {"game_date": "2026-08-18", "game": "IND @ NYL", "actual": 27, "source": "espn"},
    ]

    result = _deduplicate_history(rows)

    assert len(result) == 2
    assert result[0]["source"] == "espn"


def test_history_preserves_repeat_matchups_on_different_dates() -> None:
    rows = [
        {"game_date": "2026-08-20", "game": "IND @ MIN", "actual": 24},
        {"game_date": "2026-07-20", "game": "MIN @ IND", "actual": 29},
    ]

    assert len(_deduplicate_history(rows)) == 2
