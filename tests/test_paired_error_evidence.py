from datetime import date, timedelta

from analytics.paired_error_evidence import paired_error_evidence


def _row(day, *, actual=27, challenger=27, provenance="verified"):
    return {
        "game_date": (date(2026, 10, 1) + timedelta(days=day)).isoformat(),
        "actual": actual, "projection": 25, "minutes_shadow_projection": challenger,
        "history_provenance_status": provenance,
    }


def test_date_block_evidence_requires_independent_dates_and_import_timing():
    rows = [_row(day) for day in range(5) for _ in range(6)]
    rows.append(_row(5, actual=0, provenance="timestamp_unverified"))
    report = paired_error_evidence(rows, "minutes_shadow_projection", "projection")

    assert report["status"] == "exploratory_paired_comparison"
    assert report["samples"] == 30
    assert report["game_dates"] == 5
    assert report["mae_advantage_points"] == 2
    assert report["date_block_interval_95"] == [2, 2]
    assert report["promotion_ready"] is False


def test_many_props_on_one_date_do_not_satisfy_date_gate():
    report = paired_error_evidence(
        [_row(0) for _ in range(100)], "minutes_shadow_projection", "projection",
    )
    assert report["status"] == "insufficient_paired_evidence"
    assert report["date_block_interval_95"] is None


def test_missing_or_implausible_pairs_are_excluded():
    report = paired_error_evidence([
        _row(0, actual=101),
        _row(1, provenance="legacy_unrecorded"),
        {**_row(2), "minutes_shadow_projection": None},
        _row(3),
    ], "minutes_shadow_projection", "projection")
    assert report["samples"] == 1


def test_bootstrap_preserves_offer_weight_when_game_dates_are_uneven(monkeypatch):
    class CycleDates:
        def __init__(self, _seed):
            self.next_date = 0

        def randrange(self, count):
            selected = self.next_date % count
            self.next_date += 1
            return selected

    monkeypatch.setattr("analytics.paired_error_evidence.Random", CycleDates)
    rows = [_row(0, challenger=27) for _ in range(30)]
    rows += [{**_row(day, challenger=25), "projection": 27} for day in range(1, 5)]
    report = paired_error_evidence(rows, "minutes_shadow_projection", "projection")

    assert report["samples"] == 34
    assert report["game_dates"] == 5
    assert report["mae_advantage_points"] == 1.529
    assert report["date_block_interval_95"] == [1.529, 1.529]
