from datetime import UTC, datetime, timedelta

from analytics.linked_offer_evaluation import evaluate_linked_offers
from web.routers import results as results_router


def _row(index: int, **changes) -> dict:
    game = datetime(2026, 1, 1, 20, tzinfo=UTC) + timedelta(days=index)
    win = index % 5 != 0
    return {
        "snapshot_id": f"leg-{index}", "model_version": "v-test", "player_key": "player-one",
        "player": "Player One", "sport": "WNBA", "stat": "Points", "provider": "PrizePicks",
        "game": "A @ B", "game_start": game.isoformat(),
        "final_game_date": game.date().isoformat(),
        "feature_as_of": (game - timedelta(hours=3)).isoformat(),
        "created_at": (game - timedelta(hours=2)).isoformat(),
        "line": 20.5, "actual": 22.0 if win else 19.0,
        "direction": "Over", "board_outcome": "Win" if win else "Loss",
        "confidence": 80.0, "outcome_source": "espn", **changes,
    }


def test_chronological_linked_gate_needs_independent_holdout_and_beats_neutral():
    result = evaluate_linked_offers([_row(index) for index in range(120)], settled_board_offers=200)
    version = result["versions"][0]
    assert result["independent_settled_legs"] == 120
    assert result["settled_board_offers"] == 200
    assert version["training"]["samples"] == 90
    assert version["holdout"]["samples"] == 30
    assert version["holdout"]["brier_score"] == 0.16
    assert version["neutral_gate_passed"] is True
    assert version["market_comparison"]["ready"] is False
    assert version["review_gate_passed"] is False
    assert version["paid_release_approved"] is False


def test_duplicate_provider_lines_count_as_one_independent_outcome():
    first = _row(0)
    second = _row(0, snapshot_id="another-offer", provider="Underdog", confidence=60.0)
    result = evaluate_linked_offers([first, second])
    assert result["independent_settled_legs"] == 1
    assert result["exclusions"]["correlated_duplicate"] == 1


def test_opposite_directions_on_one_market_are_not_independent_outcomes():
    over = _row(1, actual=22.0, direction="Over", confidence=70.0)
    under = _row(1, snapshot_id="under-leg", actual=22.0, direction="Under", confidence=30.0)
    result = evaluate_linked_offers([over, under])

    assert result["independent_settled_legs"] == 1
    assert result["versioned_decisions"] == 1
    assert result["exclusions"]["correlated_duplicate"] == 1


def test_same_sporting_outcome_across_versions_is_not_counted_twice():
    result = evaluate_linked_offers([_row(0), _row(0, model_version="v-next", snapshot_id="next")])
    assert result["independent_settled_legs"] == 1
    assert result["versioned_decisions"] == 2


def test_unverified_postgame_and_wrong_day_records_are_excluded():
    game = _row(1)["game_start"]
    rows = [
        _row(0, outcome_source="import"),
        _row(1, feature_as_of=game),
        _row(2, final_game_date="2026-01-01"),
        _row(3, actual=20.5, board_outcome="Push"),
    ]
    result = evaluate_linked_offers(rows)
    assert result["independent_settled_legs"] == 0
    assert result["exclusions"] == {
        "missing_or_postgame_features": 1, "push": 1,
        "unverified_final_source": 1, "wrong_game_date": 1,
    }


def test_small_or_truncated_cohort_never_passes_review_gate():
    rows = [_row(index) for index in range(120)]
    assert evaluate_linked_offers(rows[:40])["versions"][0]["review_gate_passed"] is False
    assert evaluate_linked_offers(rows, truncated=True)["versions"][0]["review_gate_passed"] is False


def test_holdout_market_evidence_reports_missing_and_invalid_quotes():
    rows = [_row(index) for index in range(120)]
    rows[-2]["market_baseline_exclusion"] = "market_timing_unverified"
    rows[-1]["market_baseline"] = {
        "source": "The Odds API exact-line no-vig", "direction": "Over",
        "event_id": "event-119", "observed_at": rows[-1]["game_start"],
        "book_count": 2, "line": 20.5, "probability": 54.0,
    }

    coverage = evaluate_linked_offers(rows)["versions"][0]["market_evidence_coverage"]

    assert coverage == {
        "samples": 30, "paired_exact_line": 0, "unavailable": 30,
        "reasons": {
            "baseline_unavailable": 28,
            "captured_baseline_invalid_at_evaluation": 1,
            "market_timing_unverified": 1,
        },
    }


def test_paired_market_holdout_must_be_beaten_on_same_legs():
    rows = []
    for index in range(120):
        row = _row(index)
        created = datetime.fromisoformat(row["created_at"])
        row["market_baseline"] = {
            "source": "The Odds API exact-line no-vig", "probability": 50.0,
            "line": 20.5, "direction": "Over", "book_count": 3,
            "event_id": f"event-{index}",
            "observed_at": (created - timedelta(minutes=5)).isoformat(),
        }
        rows.append(row)
    result = evaluate_linked_offers(rows)
    comparison = result["versions"][0]["market_comparison"]
    assert result["versions"][0]["market_evidence_coverage"] == {
        "samples": 30, "paired_exact_line": 30, "unavailable": 0, "reasons": {},
    }
    assert comparison == {
        "paired_samples": 30, "model_brier": 0.16, "market_brier": 0.25,
        "ready": True, "passed": True,
    }
    assert result["versions"][0]["review_gate_passed"] is True
    rows[-1]["market_baseline"]["observed_at"] = rows[-1]["game_start"]
    assert evaluate_linked_offers(rows)["versions"][0]["market_comparison"]["ready"] is False


def test_read_only_results_endpoint_uses_linked_evidence(monkeypatch):
    monkeypatch.setattr(results_router.LegRecommendationSnapshotRepository, "settled_linked_rows", lambda: {
        "rows": [_row(0)], "settled_board_offers": 2, "truncated": False,
        "linkage": {"recommendation_snapshots": 3, "with_board_offer": 2, "with_settled_board_offer": 1},
    })
    result = results_router.linked_offer_evaluation()
    assert result["settled_board_offers"] == 2
    assert result["independent_settled_legs"] == 1
    assert result["linkage"]["with_settled_board_offer"] == 1
    assert result["automatic_promotion"] is False
