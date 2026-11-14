from scripts.research_nba_shadow_gap import annotate_other_appearances, classify_offers


def test_audit_separates_schedule_roster_and_exact_final():
    offers = [
        {"player": "Azurá Stevens", "team": "NYK", "game": "NYK @ UTA", "game_time": "2026-11-10T21:00:00-05:00"},
        {"player": "Other Player", "team": "NYK", "game": "NYK @ UTA", "game_time": "2026-11-10T21:00:00-05:00"},
        {"player": "Player Three", "team": "BOS", "game": "BOS @ MIA", "game_time": "2026-11-10T21:00:00-05:00"},
    ]
    games = [{"game": "NY@UTAH"}, {"game": "BOS@MIA"}]
    outcomes = [{"game": "NY@UTAH"}]
    finals = [{"player": "Azura Stevens", "game": "NY@UTAH", "sport": "NBA", "stat": "Points"}]

    rows = classify_offers(offers, games, outcomes, finals)
    assert [row["reason"] for row in rows] == [
        "exact_player_game_final_available",
        "player_absent_from_official_points_roster",
        "game_not_in_official_final_outcomes",
    ]


def test_audit_detects_player_in_other_official_game():
    offer = {"player": "Player One", "game": "BOS @ NYK", "game_time": "2026-11-10T19:00:00-05:00"}
    rows = classify_offers(
        [offer], [{"game": "BOS@NY"}, {"game": "UTA@MIA"}],
        [{"game": "BOS@NY"}],
        [{"player": "Player One", "game": "UTA@MIA", "sport": "NBA", "stat": "Points"}],
    )
    assert rows[0]["reason"] == "player_in_other_game_that_day"
    assert rows[0]["other_game"] == "UTA@MIA"


def test_other_appearances_normalize_provider_team_aliases_without_inferring_dnp():
    rows = [{"player": "Trey Murphy III", "team": "NOP", "reason": "player_absent_from_official_points_roster"}]
    annotate_other_appearances(rows, [
        {"player": "Trey Murphy III", "team": "NO", "game_date": "2026-11-08"},
    ])
    assert rows[0]["seen_with_offered_team_on_other_date"] is True
    assert rows[0]["official_appearances_on_checked_dates"] == 1
    assert rows[0]["reason"] == "player_absent_from_official_points_roster"
