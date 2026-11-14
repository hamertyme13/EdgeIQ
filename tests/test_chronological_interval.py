from datetime import date, timedelta

from analytics.chronological_interval import evaluate_chronological_interval


def _row(day: int, *, actual: float = 21, projection: float = 20, provenance: str = "verified") -> dict:
    return {
        "game_date": (date(2026, 10, 1) + timedelta(days=day)).isoformat(),
        "actual": actual, "projection": projection,
        "history_provenance_status": provenance,
    }


def test_interval_requires_earlier_dates_and_verified_history_import():
    rows = [_row(day, actual=21) for day in range(5) for _ in range(6)]
    rows.extend(_row(5, actual=22) for _ in range(2))
    rows.append(_row(5, actual=100, provenance="timestamp_unverified"))

    report = evaluate_chronological_interval(rows)

    assert report["status"] == "insufficient_later_games"
    assert report["eligible_samples"] == 32
    assert report["evaluated"] == 2
    assert report["inside"] == 0
    assert report["coverage_pct"] is None
    assert report["daily"] == [{
        "game_date": "2026-10-06", "calibration_samples": 30,
        "radius": 1.0, "evaluated": 2, "inside": 0,
    }]


def test_interval_does_not_learn_from_same_day_results():
    earlier = [_row(day) for day in range(5) for _ in range(6)]
    current = [_row(5, actual=99) for _ in range(10)] + [_row(5, actual=21)]
    later = [_row(6, actual=21)]

    report = evaluate_chronological_interval([*later, *current, *earlier])

    assert report["daily"][0]["radius"] == 1.0
    assert report["daily"][1]["calibration_samples"] == 41
    assert report["daily"][1]["radius"] > 1.0


def test_interval_reports_coverage_only_after_two_later_dates_and_ten_outcomes():
    rows = [_row(day) for day in range(5) for _ in range(6)]
    rows += [_row(day, actual=21) for day in (5, 6) for _ in range(5)]
    report = evaluate_chronological_interval(rows)
    assert report["status"] == "exploratory_chronological"
    assert report["evaluated"] == 10
    assert report["evaluated_game_dates"] == 2
    assert report["coverage_pct"] == 100.0


def test_interval_withholds_coverage_when_thin_or_unverified():
    report = evaluate_chronological_interval([_row(day) for day in range(5)])
    assert report["status"] == "insufficient_pregame_evidence"
    assert report["coverage_pct"] is None
    assert evaluate_chronological_interval([_row(day, provenance="timestamp_unverified") for day in range(6)])["eligible_samples"] == 0


def test_nba_points_interval_excludes_implausible_totals():
    report = evaluate_chronological_interval(
        [_row(0, actual=101), _row(1, projection=105), _row(2, actual=25)],
        maximum_actual=100,
    )
    assert report["eligible_samples"] == 1
