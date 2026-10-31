from web.application.research_service import player_team_context


def test_team_context_uses_latest_verified_final_without_current_offer():
    rows = [
        {"team": "OLD", "game_date": "2026-10-24", "source": "manual", "status": "played"},
        {"team": "PHI", "game_date": "2026-10-23", "source": "espn", "status": "played"},
        {"team": "BOS", "game_date": "2026-10-20", "source": "nba_api", "status": "played"},
    ]

    assert player_team_context(rows, None) == {
        "team": "PHI", "source": "latest_verified_final", "as_of": "2026-10-23",
    }


def test_current_offer_team_takes_precedence_over_history():
    history = [{"team": "PHI", "game_date": "2026-10-23", "source": "espn"}]

    assert player_team_context(history, {"team": "NYK", "game_time": "2026-10-27T00:00:00Z"}) == {
        "team": "NYK", "source": "current_provider_offer", "as_of": "2026-10-27T00:00:00Z",
    }


def test_unverified_history_does_not_claim_a_team():
    assert player_team_context([{"team": "PHI", "game_date": "2026-10-23", "source": "manual"}], None) == {
        "team": None, "source": "unavailable", "as_of": None,
    }
