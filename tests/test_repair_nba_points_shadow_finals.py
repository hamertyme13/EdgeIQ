from scripts.repair_nba_points_shadow_finals import coverage_reasons, exact_recovery_rows


def test_recovery_requires_exact_player_matchup_and_eastern_date():
    pending = [{"player": "Azurá Stevens", "game": "NYK @ UTA",
                "game_time": "2026-11-10T21:00:00-05:00"}]
    base = {"player": "Azura Stevens", "game": "NY@UTAH", "game_date": "2026-11-10",
            "sport": "NBA", "stat": "Points", "source": "espn", "status": "played", "actual": 20}
    rows = [base, {**base, "game": "NY@BOS"}, {**base, "game_date": "2026-11-11"},
            {**base, "source": "projection_estimate"}, {**base, "stat": "Rebounds"}]
    assert exact_recovery_rows(pending, rows) == [base]


def test_coverage_diagnoses_absence_without_assigning_an_outcome():
    pending = [
        {"player": "Azurá Stevens", "game": "NYK @ UTA", "game_time": "2026-11-10T21:00:00-05:00"},
        {"player": "Other Player", "game": "NYK @ UTA", "game_time": "2026-11-10T21:00:00-05:00"},
        {"player": "Unknown Player", "game": "BOS @ MIA", "game_time": "2026-11-10T21:00:00-05:00"},
    ]
    finals = [{"player": "Azura Stevens", "game": "NY@BOS", "sport": "NBA", "stat": "Points"}]
    games = [{"game": "NY@UTAH"}]

    assert coverage_reasons(pending, finals, games) == {
        "matchup_absent_from_official_schedule": 1,
        "player_absent_from_official_points_box_score": 1,
        "player_in_different_official_game": 1,
    }
