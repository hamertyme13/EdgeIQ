from scripts.audit_nba_points_shadow_pending import classify_pending


def test_pending_audit_distinguishes_feed_coverage_from_match_failure():
    pending = [
        {"player": "Azurá Stevens", "game_time": "2026-11-10T19:30:00-05:00"},
        {"player": "Other Player", "game_time": "2026-11-10T19:30:00-05:00"},
        {"player": "Third Player", "game_time": "2026-11-09T19:30:00-05:00"},
    ]
    finals = [{"player": "Azura Stevens", "game_date": "2026-11-10"}]
    report = classify_pending(pending, finals)
    assert report["by_reason"] == {
        "nba_points_feed_absent_for_day": 1,
        "player_day_final_exists_match_needs_review": 1,
        "player_day_points_final_absent": 1,
    }
    assert report["pending"] == 3


def test_nearby_date_is_flagged_for_review_not_treated_as_a_verified_match():
    report = classify_pending(
        [{"player": "Test Player", "game": "NYK @ UTA", "game_time": "2026-11-10T21:00:00-05:00"}],
        [{"player": "Test Player", "game": "NY@UTAH", "game_date": "2026-11-11"}],
    )
    assert report["by_reason"] == {"same_matchup_nearby_day_requires_review": 1}


def test_nearby_player_final_for_another_game_does_not_suggest_date_repair():
    report = classify_pending(
        [{"player": "Test Player", "game": "NYK @ UTA", "game_time": "2026-11-10T21:00:00-05:00"}],
        [{"player": "Test Player", "game": "NY@BOS", "game_date": "2026-11-11"}],
    )
    assert report["by_reason"] == {"nba_points_feed_absent_for_day": 1}
