from analytics.nba_points_provenance import history_import_provenance
from analytics.probabilistic_forecast import forecast_prop


def test_history_import_provenance_distinguishes_missing_invalid_and_late():
    rows = [
        {"imported_at": "2026-10-21T20:00:00Z"},
        {"imported_at": "2026-10-22T16:01:00Z"},
        {"imported_at": "not-a-timestamp"},
        {"imported_at": "2026-10-20"},
        {},
    ]
    result = history_import_provenance(rows, "2026-10-22T12:00:00-04:00")
    assert result == {
        "status": "imported_after_lock", "rows": 5,
        "missing_import_time": 1, "invalid_import_time": 2,
        "imported_after_lock": 1,
        "latest_imported_at": "2026-10-22T16:01:00+00:00",
    }


def test_nba_points_forecast_locks_history_import_provenance():
    history = [
        {
            "actual": 20 + index, "status": "played", "season_type": "regular",
            "game_date": f"2026-10-{21 - index:02d}", "game": f"A@B-{index}",
            "imported_at": f"2026-10-{21 - index:02d}T23:00:00Z",
        }
        for index in range(6)
    ]
    forecast = forecast_prop(
        "Sample Player", "NBA", "Points", 20.5,
        history=history, game_time="2026-10-23",
    )
    provenance = forecast.snapshot()["features"]["nba_points_history_provenance"]
    assert provenance["status"] == "verified"
    assert provenance["rows"] == 6
    assert provenance["latest_imported_at"] == "2026-10-21T23:00:00+00:00"
