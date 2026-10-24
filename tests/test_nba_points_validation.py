from datetime import UTC, datetime, timedelta

from analytics.nba_points_validation import evaluate_nba_points_predictions
from web.routers.players import nba_points_validation


def _row(key: str = "market-1", *, version: str = "points-v1", actual: float = 27, line: float = 24.5, projection: float = 26, probability: float = 70) -> dict:
    game = datetime(2026, 10, 23, 19, tzinfo=UTC)
    prediction = game - timedelta(hours=6)
    return {
        "id": 1,
        "independent_market_key": key,
        "player_identity_id": 12,
        "sport": "NBA",
        "stat": "Points",
        "platform": "PrizePicks",
        "line": line,
        "direction": "Over",
        "projection": projection,
        "projection_source": "verified_history_distribution",
        "probability": probability,
        "model_version": version,
        "feature_as_of": prediction - timedelta(minutes=2),
        "feature_snapshot": {
            "source": "verified_history_distribution",
            "features": {"recent_5_mean": 25, "verified_games": 15, "season_end": "2026-10-21"},
        },
        "predicted_at": prediction,
        "game_time": game.isoformat(),
        "settled_at": game + timedelta(hours=3),
        "result": "Win",
        "actual": actual,
        "outcome_source": "espn",
    }


def test_locked_validation_uses_paired_line_and_pregame_baseline():
    first = _row()
    second = _row("market-2", actual=20, projection=22, probability=60)
    second["result"] = "Loss"
    second["feature_snapshot"]["features"]["recent_5_mean"] = 21
    report = evaluate_nba_points_predictions([second, first])

    assert report["eligible_independent"] == 2
    assert report["evidence_maturity"] == "exploratory"
    version = report["versions"][0]
    assert version["metrics"]["mae"] == 1.5
    assert version["metrics"]["rmse"] == 1.581
    assert version["metrics"]["brier"] == 0.225
    assert version["paired_baselines"]["exact_line"]["samples"] == 2
    assert version["paired_baselines"]["exact_line"]["mae"] == 3.5
    assert version["paired_baselines"]["locked_recent_5_mean"]["mae"] == 1.5
    assert version["calibration_buckets"]
    assert version["by_line"][0]["label"] == "15-24.5"
    assert version["by_history_size"][0]["label"] == "10-19"
    assert version["matchup_difficulty"]["status"] == "unavailable"
    assert version["promotion_ready"] is False
    assert report["challenger_comparison"]["status"] == "not_paired"
    assert report["ev"] is None


def test_postgame_features_duplicates_pushes_and_conflicts_are_excluded():
    clean = _row()
    duplicate = {**clean, "id": 2, "predicted_at": clean["predicted_at"] + timedelta(minutes=1)}
    postgame = _row("future")
    postgame["feature_snapshot"]["features"]["season_end"] = "2026-10-23"
    push = _row("push", actual=24.5)
    push["result"] = "Push"
    wrong = _row("wrong", actual=20)
    old = _row("old")
    old["feature_as_of"] = old["game_time"]
    report = evaluate_nba_points_predictions([wrong, postgame, duplicate, push, old, clean])

    assert report["eligible_independent"] == 1
    assert report["excluded"]["duplicate_market"] == 1
    assert report["excluded"]["postgame_history"] == 1
    assert report["excluded"]["unverified_final"] == 1
    assert report["excluded"]["conflicting_result"] == 1
    assert report["excluded"]["not_locked_before_game"] == 1


def test_market_prior_and_unverified_source_do_not_validate_model():
    prior = _row()
    prior["feature_snapshot"]["source"] = "market_prior"
    unverified = _row("unverified")
    unverified["outcome_source"] = "projection_estimate"
    report = evaluate_nba_points_predictions([prior, unverified])
    assert report["status"] == "insufficient_locked_evidence"
    assert report["versions"] == []
    assert report["excluded"] == {"no_locked_points_forecast": 1, "unverified_final": 1}


def test_malformed_feature_payload_fails_closed():
    row = _row()
    row["feature_snapshot"]["features"] = ["unexpected"]
    report = evaluate_nba_points_predictions([row])
    assert report["eligible_independent"] == 0
    assert report["excluded"] == {"no_locked_points_forecast": 1}


def test_route_uses_bounded_repository_reader(monkeypatch):
    from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository

    monkeypatch.setattr(PredictionLedgerRepository, "nba_points_validation_rows", lambda: [_row()])
    assert nba_points_validation()["eligible_independent"] == 1
