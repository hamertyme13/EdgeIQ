from datetime import date

from web.application.season_history_service import season_window, start_season_history_sync


def test_season_window_uses_calendar_season_for_wnba_and_nfl() -> None:
    assert season_window("WNBA", date(2026, 8, 20)) == (date(2026, 5, 1), date(2026, 8, 20))
    assert season_window("NFL", date(2026, 8, 20)) == (date(2026, 7, 15), date(2026, 8, 20))


def test_season_window_crosses_year_for_nba() -> None:
    assert season_window("NBA", date(2026, 2, 2)) == (date(2025, 9, 15), date(2026, 2, 2))


def test_season_sync_rejects_unsupported_sport_in_plain_language() -> None:
    result = start_season_history_sync("TENNIS")
    assert result["accepted"] is False
    assert result["message"] == "Choose WNBA, NBA, NFL, MLB, or NHL."
