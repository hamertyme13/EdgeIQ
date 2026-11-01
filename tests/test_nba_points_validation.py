from datetime import UTC, datetime, timedelta

from analytics.nba_points_validation import evaluate_nba_points_predictions
from web.routers.players import nba_points_validation


def _row(key: str = "market-1", *, version: str = "points-v1", actual: float = 27, line: float = 24.5, projection: float = 26, probability: float = 70) -> dict:
    game = datetime(2026, 10, 23, 19, tzinfo=UTC)
    prediction = game - timedelta(hours=6)
    return {
        "id": 1,
        "independent_market_key": key,
        "player_identity_id": 12 + sum(ord(char) for char in key),
        "player": f"Player {key}",
        "game": "BOS @ NYK",
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


def test_late_history_import_cannot_qualify_locked_nba_points_forecast():
    late = _row("late-import")
    late["feature_snapshot"]["features"]["nba_points_history_provenance"] = {
        "status": "imported_after_lock", "imported_after_lock": 1,
    }
    verified = _row("verified-import")
    verified["feature_snapshot"]["features"]["nba_points_history_provenance"] = {
        "status": "verified", "imported_after_lock": 0, "invalid_import_time": 0,
    }
    missing = _row("missing-import")
    missing["feature_snapshot"]["features"]["nba_points_history_provenance"] = {
        "status": "timestamp_unverified", "missing_import_time": 1,
    }

    report = evaluate_nba_points_predictions([late, verified, missing])
    assert report["excluded"]["history_imported_after_lock"] == 1
    assert report["eligible_independent"] == 2
    assert report["versions"][0]["history_import_provenance"] == {
        "timestamp_unverified": 1, "verified": 1,
    }


def test_evidence_maturity_requires_verified_history_timing_across_game_dates():
    rows = [_row(f"player-{index}") for index in range(100)]
    for index, row in enumerate(rows):
        row["game_time"] = (datetime(2026, 10, 23, 19, tzinfo=UTC) + timedelta(days=index % 5)).isoformat()
        row["settled_at"] = datetime.fromisoformat(row["game_time"]) + timedelta(hours=3)
    legacy = evaluate_nba_points_predictions(rows)
    assert legacy["eligible_independent"] == 100
    assert legacy["pregame_provenance_verified_independent"] == 0
    assert legacy["evidence_maturity"] == "exploratory"

    for row in rows:
        row["feature_snapshot"]["features"]["nba_points_history_provenance"] = {
            "status": "verified", "imported_after_lock": 0, "invalid_import_time": 0,
        }
    verified = evaluate_nba_points_predictions(rows)
    assert verified["pregame_provenance_verified_independent"] == 100
    assert verified["pregame_provenance_verified_game_dates"] == 5
    assert verified["evidence_maturity"] == "initial_evaluation"


def test_locked_minutes_challenger_uses_only_same_settled_offers():
    first = _row(actual=27, projection=26)
    second = _row("market-2", actual=20, projection=22, probability=60)
    second["result"] = "Loss"
    for row, value in ((first, 27), (second, 21)):
        row["feature_snapshot"]["features"]["nba_points_minutes_shadow"] = {
            "model_version": "nba-points-verified-minutes-shadow-v1",
            "shadow_only": True, "status": "shadow_evaluation", "sample_size": 7,
            "expected_points": value,
        }
    unpaired = _row("market-3", actual=30, projection=20)

    report = evaluate_nba_points_predictions([first, second, unpaired])

    assert report["eligible_independent"] == 3
    assert report["versions"][0]["paired_baselines"]["locked_minutes_shadow"]["samples"] == 2
    comparison = report["challenger_comparison"]
    assert comparison["status"] == "paired_exploratory"
    assert comparison["versions"][0]["samples"] == 2
    assert comparison["versions"][0]["champion"]["mae"] == 1.5
    assert comparison["versions"][0]["minutes_shadow"]["mae"] == 0.5
    assert report["versions"][0]["promotion_ready"] is False


def test_locked_shot_volume_challenger_uses_its_own_paired_offers():
    first = _row(actual=27, projection=26)
    second = _row("market-2", actual=20, projection=22, probability=60)
    second["result"] = "Loss"
    for row, value in ((first, 27), (second, 21)):
        row["feature_snapshot"]["features"]["nba_points_shot_volume_shadow"] = {
            "model_version": "nba-points-verified-shot-volume-shadow-v1",
            "shadow_only": True, "status": "shadow_evaluation", "sample_size": 7,
            "expected_points": value,
        }
    report = evaluate_nba_points_predictions([first, second, _row("market-3")])

    assert report["versions"][0]["paired_baselines"]["locked_shot_volume_shadow"]["samples"] == 2
    comparison = report["challenger_comparison"]["versions"][0]
    assert comparison["samples"] == 0
    assert comparison["shot_volume"]["samples"] == 2
    assert comparison["shot_volume"]["champion"]["mae"] == 1.5
    assert comparison["shot_volume"]["shot_volume_shadow"]["mae"] == 0.5
    assert report["versions"][0]["promotion_ready"] is False


def test_matchup_segments_require_locked_pregame_versioned_evidence():
    valid = _row()
    valid["feature_snapshot"]["features"]["nba_points_opponent_defense"] = {
        "model_version": "nba-team-defense-rank-v1", "shadow_only": True,
        "evidence_as_of": valid["predicted_at"] - timedelta(minutes=5),
        "advantage_score": 80, "opponent_sample_size": 7, "ranked_teams": 12,
    }
    late = _row("late")
    late["feature_snapshot"]["features"]["nba_points_opponent_defense"] = {
        **valid["feature_snapshot"]["features"]["nba_points_opponent_defense"],
        "evidence_as_of": late["predicted_at"] + timedelta(minutes=1),
    }
    report = evaluate_nba_points_predictions([valid, late])
    segment = report["versions"][0]["matchup_difficulty"]
    assert segment["status"] == "descriptive_segments"
    assert segment["samples"] == 1
    assert segment["segments"][0]["label"] == "Higher points allowed"
    assert segment["segments"][0]["samples"] == 1
    assert report["versions"][0]["promotion_ready"] is False


def test_matchup_segments_include_fractional_scores_and_separate_board_evidence():
    rows = []
    for key, score, origin in (
        ("lower", 33.5, "prospective_board"),
        ("middle", 66.5, "prospective_board"),
        ("higher", 100, "placed_entry"),
    ):
        row = _row(key)
        row["evidence_origin"] = origin
        row["feature_snapshot"]["features"]["nba_points_opponent_defense"] = {
            "model_version": "nba-team-defense-rank-v1", "shadow_only": True,
            "evidence_as_of": row["predicted_at"] - timedelta(minutes=5),
            "advantage_score": score, "opponent_sample_size": 7, "ranked_teams": 12,
        }
        rows.append(row)

    report = evaluate_nba_points_predictions(rows)
    matchup = report["versions"][0]["matchup_difficulty"]
    assert matchup["samples"] == 3
    assert sum(segment["samples"] for segment in matchup["segments"]) == 3
    assert [segment["label"] for segment in matchup["segments"]] == [
        "Middle", "Higher points allowed",
    ]
    assert matchup["prospective_board"]["samples"] == 2
    assert sum(segment["samples"] for segment in matchup["prospective_board"]["segments"]) == 2
    assert matchup["prospective_board"]["segments"][0]["paired_baselines"]["exact_line"]["samples"] == 2
    assert report["versions"][0]["promotion_ready"] is False


def test_matchup_board_segment_survives_earlier_placed_entry_for_same_player_game():
    placed = _row("placed")
    placed["evidence_origin"] = "placed_entry"
    board = _row("board")
    board["player"] = placed["player"]
    board["evidence_origin"] = "prospective_board"
    board["predicted_at"] = placed["predicted_at"] + timedelta(minutes=1)
    board["feature_snapshot"]["features"]["nba_points_opponent_defense"] = {
        "model_version": "nba-team-defense-rank-v1", "shadow_only": True,
        "evidence_as_of": board["predicted_at"] - timedelta(minutes=5),
        "advantage_score": 80, "opponent_sample_size": 7, "ranked_teams": 12,
    }

    report = evaluate_nba_points_predictions([placed, board])
    matchup = report["versions"][0]["matchup_difficulty"]
    assert report["eligible_independent"] == 1
    assert matchup["samples"] == 0
    assert matchup["prospective_board"]["samples"] == 1
    assert matchup["prospective_board"]["segments"][0]["label"] == "Higher points allowed"


def test_different_lines_and_directions_for_one_player_game_count_once():
    first = _row()
    later = _row("another-market", line=29.5, projection=28, probability=55)
    later.update({
        "player_identity_id": first["player_identity_id"] + 1,
        "player": first["player"],
        "platform": "Underdog",
        "direction": "Under",
        "result": "Win",
        "predicted_at": first["predicted_at"] + timedelta(minutes=1),
    })
    later["feature_as_of"] = first["feature_as_of"]

    report = evaluate_nba_points_predictions([later, first])

    assert report["eligible_independent"] == 1
    assert report["excluded"]["duplicate_player_game"] == 1
    assert report["versions"][0]["metrics"]["mae"] == 1.0


def test_missing_player_identity_cannot_masquerade_as_independent_market():
    row = _row()
    row["player_identity_id"] = None
    row["player"] = ""

    report = evaluate_nba_points_predictions([row])

    assert report["eligible_independent"] == 0
    assert report["excluded"]["missing_player_identity"] == 1


def test_two_model_versions_share_one_independent_player_game():
    champion = _row()
    challenger = _row("another-market", version="points-v2")
    challenger["player"] = champion["player"]
    challenger["player_identity_id"] = champion["player_identity_id"]

    report = evaluate_nba_points_predictions([champion, challenger])

    assert report["eligible_independent"] == 1
    assert report["evidence_maturity"] == "exploratory"
    assert len(report["versions"]) == 2
    assert all(version["metrics"]["samples"] == 1 for version in report["versions"])


def test_board_and_entry_outcomes_overlap_only_once_in_total_evidence():
    placed = _row()
    board = _row("board-market", version="nba-points-board/points-v1")
    board["player"] = placed["player"]
    board["evidence_origin"] = "prospective_board"

    report = evaluate_nba_points_predictions([placed, board])

    assert report["eligible_independent"] == 1
    assert report["evidence_origins"] == {"placed_entry": 1, "prospective_board": 1}
    assert len(report["versions"]) == 2


def test_same_version_keeps_prospective_board_metrics_when_placed_entry_overlaps():
    placed = _row()
    board = _row("board-market")
    board["player"] = placed["player"]
    board["player_identity_id"] = placed["player_identity_id"]
    board["evidence_origin"] = "prospective_board"
    board["projection"] = 25
    board["predicted_at"] = placed["predicted_at"] + timedelta(minutes=1)

    report = evaluate_nba_points_predictions([placed, board])

    assert report["eligible_independent"] == 1
    assert report["evidence_origins"] == {"placed_entry": 1, "prospective_board": 1}
    version = report["versions"][0]
    assert version["evidence_origin"] == "mixed"
    assert version["metrics"]["samples"] == 1
    assert version["by_evidence_origin"]["placed_entry"]["metrics"]["mae"] == 1
    assert version["by_evidence_origin"]["prospective_board"]["metrics"]["mae"] == 2
    assert version["chronological_board_holdout"]["status"] == "insufficient_board_evidence"


def test_chronological_holdout_uses_later_board_games_only():
    rows = []
    for day in range(10):
        for player in range(4):
            row = _row(f"board-{day}-{player}", actual=27, projection=26)
            game = datetime(2026, 10, 1 + day, 19, tzinfo=UTC)
            row.update({
                "game_time": game.isoformat(),
                "predicted_at": game - timedelta(hours=6),
                "feature_as_of": game - timedelta(hours=7),
                "settled_at": game + timedelta(hours=3),
                "evidence_origin": "prospective_board",
            })
            row["feature_snapshot"]["features"]["season_end"] = (game - timedelta(days=1)).date().isoformat()
            if day >= 7:
                row["projection"] = 24
                row["feature_snapshot"]["features"]["nba_points_minutes_shadow"] = {
                    "model_version": "nba-points-verified-minutes-shadow-v1",
                    "shadow_only": True, "status": "shadow_evaluation", "sample_size": 7,
                    "expected_points": 27,
                }
                row["feature_snapshot"]["features"]["nba_points_shot_volume_shadow"] = {
                    "model_version": "nba-points-verified-shot-volume-shadow-v1",
                    "shadow_only": True, "status": "shadow_evaluation", "sample_size": 7,
                    "expected_points": 28,
                }
            rows.append(row)
    placed = _row("placed-outlier", actual=0, projection=90)
    placed["feature_snapshot"]["features"]["season_end"] = "2026-10-21"
    placed["result"] = "Loss"

    report = evaluate_nba_points_predictions(rows + [placed])
    holdout = report["versions"][0]["chronological_board_holdout"]

    assert holdout["status"] == "exploratory_holdout"
    assert holdout["cutoff_game_date"] == "2026-10-08"
    assert holdout["earlier_samples"] == 28
    assert holdout["later_samples"] == 12
    assert holdout["forecast"]["mae"] == 3
    assert holdout["paired_minutes"]["samples"] == 12
    assert holdout["paired_minutes"]["minutes_shadow"]["mae"] == 0
    assert holdout["paired_shot_volume"]["samples"] == 12
    assert holdout["paired_shot_volume"]["champion"]["mae"] == 3
    assert holdout["paired_shot_volume"]["shot_volume_shadow"]["mae"] == 1
    assert holdout["promotion_ready"] is False


def test_unversioned_or_implausible_minutes_shadow_is_not_compared():
    row = _row()
    row["feature_snapshot"]["features"]["nba_points_minutes_shadow"] = {
        "model_version": "legacy", "shadow_only": True, "status": "shadow_evaluation",
        "sample_size": 7, "expected_points": 150,
    }
    report = evaluate_nba_points_predictions([row])

    assert report["eligible_independent"] == 1
    assert report["challenger_comparison"]["status"] == "not_paired"
    assert report["versions"][0]["paired_baselines"]["locked_minutes_shadow"]["samples"] == 0


def test_unversioned_or_implausible_shot_volume_shadow_is_not_compared():
    row = _row()
    row["feature_snapshot"]["features"]["nba_points_shot_volume_shadow"] = {
        "model_version": "legacy", "shadow_only": True, "status": "shadow_evaluation",
        "sample_size": 7, "expected_points": 150,
    }
    report = evaluate_nba_points_predictions([row])

    assert report["challenger_comparison"]["status"] == "not_paired"
    assert report["versions"][0]["paired_baselines"]["locked_shot_volume_shadow"]["samples"] == 0


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
    assert report["excluded"]["duplicate_player_game"] == 1
    assert report["excluded"]["postgame_history"] == 1
    assert report["excluded"]["unverified_final"] == 1
    assert report["excluded"]["conflicting_result"] == 1
    assert report["excluded"]["not_locked_before_game"] == 1


def test_late_eastern_tipoff_rejects_same_day_history_despite_next_utc_date():
    row = _row()
    row["game_time"] = "2026-10-24T00:30:00+00:00"
    row["feature_as_of"] = "2026-10-23T19:00:00+00:00"
    row["predicted_at"] = "2026-10-23T19:02:00+00:00"
    row["settled_at"] = "2026-10-24T04:00:00+00:00"
    row["feature_snapshot"]["features"]["season_end"] = "2026-10-23"

    rejected = evaluate_nba_points_predictions([row])
    assert rejected["eligible_independent"] == 0
    assert rejected["excluded"]["postgame_history"] == 1

    row["feature_snapshot"]["features"]["season_end"] = "2026-10-22"
    accepted = evaluate_nba_points_predictions([row])
    assert accepted["eligible_independent"] == 1
    assert accepted["versions"][0]["first_game"] == "2026-10-23"


def test_suspected_database_timezone_mismatch_is_excluded_separately():
    row = _row()
    row["predicted_at"] = row["feature_as_of"] - timedelta(hours=4)

    report = evaluate_nba_points_predictions([row])

    assert report["eligible_independent"] == 0
    assert report["excluded"]["suspected_timestamp_timezone_mismatch"] == 1


def test_market_prior_and_unverified_source_do_not_validate_model():
    prior = _row()
    prior["feature_snapshot"]["source"] = "market_prior"
    unverified = _row("unverified")
    unverified["outcome_source"] = "projection_estimate"
    report = evaluate_nba_points_predictions([prior, unverified])
    assert report["status"] == "insufficient_locked_evidence"
    assert report["versions"] == []
    assert report["excluded"] == {"market_prior_only": 1, "unverified_final": 1}
    assert report["excluded_by_origin"]["placed_entry"] == report["excluded"]


def test_malformed_feature_payload_fails_closed():
    row = _row()
    row["feature_snapshot"]["features"] = ["unexpected"]
    report = evaluate_nba_points_predictions([row])
    assert report["eligible_independent"] == 0
    assert report["excluded"] == {"no_locked_points_forecast": 1}


def test_board_market_priors_are_reported_separately_from_placed_entries():
    board = _row("board")
    board["evidence_origin"] = "prospective_board"
    board["feature_snapshot"]["source"] = "market_prior"
    placed = _row("placed")
    report = evaluate_nba_points_predictions([board, placed])
    assert report["observed_settled_by_origin"] == {"placed_entry": 1, "prospective_board": 1}
    assert report["excluded_by_origin"] == {"prospective_board": {"market_prior_only": 1}}
    assert report["evidence_origins"] == {"placed_entry": 1}


def test_route_uses_bounded_repository_reader(monkeypatch):
    from repository.repositories.model_rehabilitation_repository import ModelRehabilitationRepository
    from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository

    monkeypatch.setattr(PredictionLedgerRepository, "nba_points_validation_rows", lambda: [_row()])
    monkeypatch.setattr(ModelRehabilitationRepository, "nba_points_board_validation_rows", lambda: [])
    assert nba_points_validation()["eligible_independent"] == 1
