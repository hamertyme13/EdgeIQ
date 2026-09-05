from datetime import UTC, datetime

from analytics.game_features import prop_opportunity_context
from analytics.game_model_evaluation import chronological_game_evaluation, evaluate_game_predictions
from analytics.game_model_registry import GAME_CONTEXT_CHALLENGER_VERSION, promotion_decision
from analytics.game_prediction import predict_game
from analytics.probabilistic_forecast import forecast_prop
from repository.repositories.game_prediction_repository import GamePredictionRepository
from services.game_intelligence import latest_slate_predictions


def _features(**overrides):
    return {
        "sport": "WNBA",
        "game_id": "game-intelligence-test",
        "game": "MIN @ DAL",
        "away_team": "MIN",
        "home_team": "DAL",
        "game_start": "2026-09-05T00:00:00Z",
        "market_home_probability": 0.42,
        "historical_home_probability": 0.55,
        "historical_sample_size": 20,
        "market_home_margin": -3.5,
        "market_total": 164.5,
        "expected_pace": 81.2,
        "data_quality_score": 85,
    } | overrides


def test_game_prediction_probabilities_are_bounded_and_sum_to_one():
    prediction = predict_game(_features(market_home_probability=1.8))
    assert 0.0 <= prediction.home_win_probability <= 1.0
    assert 0.0 <= prediction.away_win_probability <= 1.0
    assert round(prediction.home_win_probability + prediction.away_win_probability, 8) == 1.0


def test_game_prediction_uses_market_fallback_when_history_is_missing():
    prediction = predict_game(_features(historical_sample_size=0, historical_home_probability=None))
    assert prediction.home_win_probability == 0.42
    assert prediction.evidence["prediction_method"] == "no_vig_market_baseline"


def test_game_context_changes_opportunity_but_never_confidence():
    context = prop_opportunity_context(
        "NFL", "Receiving Yards", "DAL", {
            "home_team": "DAL", "away_team": "PHI", "expected_margin": -10,
            "expected_total": 49, "blowout_probability": 0.3, "game_script": "away_leading",
        }, expected_opportunities=8,
    )
    assert context["opportunity_factor"] > 1.0
    assert context["confidence_delta"] == 0.0
    assert context["shadow_only"] is True
    assert context["adjustments"][0]["treatment"] == "residual"


def test_neutral_game_context_has_no_opportunity_adjustment():
    context = prop_opportunity_context("NFL", "Receiving Yards", "DAL", {
        "home_team": "DAL", "away_team": "PHI", "expected_margin": 0,
        "expected_total": 44, "blowout_probability": 0.1, "game_script": "neutral",
    }, expected_opportunities=8)
    assert context["opportunity_factor"] == 1.0
    assert context["adjustments"] == []


def test_wnba_pace_and_blowout_adjust_opportunity_not_confidence():
    context = prop_opportunity_context("WNBA", "Points", "DAL", {
        "home_team": "DAL", "away_team": "MIN", "expected_margin": 12,
        "expected_total": 170, "expected_pace": 84, "blowout_probability": 0.45,
        "game_script": "home_leading",
    }, expected_minutes=34, expected_opportunities=18)
    assert {row["metric"] for row in context["adjustments"]} == {"minutes", "possessions"}
    assert context["confidence_delta"] == 0.0
    assert context["shadow_only"] is True


def test_home_favorite_prediction_has_higher_home_score():
    prediction = predict_game(_features(market_home_probability=0.7, market_home_margin=5.5))
    assert prediction.home_win_probability > prediction.away_win_probability
    assert prediction.expected_home_points > prediction.expected_away_points


def test_prop_forecast_keeps_champion_projection_and_stores_shadow_context():
    history = [{"actual": value, "game_date": f"2026-07-{index:02d}", "targets": 8} for index, value in enumerate(range(15, 35), start=1)]
    baseline = forecast_prop("Player", "NFL", "Receiving Yards", 24.5, history=history, team="DAL", game="PHI @ DAL")
    aware = forecast_prop("Player", "NFL", "Receiving Yards", 24.5, history=history, team="DAL", game="PHI @ DAL", game_prediction={
        "home_team": "DAL", "away_team": "PHI", "expected_margin": -10,
        "expected_total": 49, "blowout_probability": 0.3, "game_script": "away_leading",
    })
    assert aware.projection == baseline.projection
    assert aware.probability == baseline.probability
    assert aware.features["game_aware_shadow_projection"] != aware.projection
    assert aware.features["game_intelligence"]["confidence_delta"] == 0.0


def test_game_prediction_persistence_is_idempotent_and_settleable():
    generated_at = datetime.now(UTC).isoformat()
    snapshot = predict_game(_features(), model_version=GAME_CONTEXT_CHALLENGER_VERSION).snapshot() | {"generated_at": generated_at}
    first = GamePredictionRepository.save(snapshot)
    second = GamePredictionRepository.save(snapshot)
    assert first["id"] == second["id"]
    assert GamePredictionRepository.settle("game-intelligence-test", 78, 84, "official_test") >= 1
    settled = next(row for row in GamePredictionRepository.latest(sport="WNBA") if row["id"] == first["id"])
    assert settled["actual_home_win"] == 0.0
    assert settled["actual_margin"] == -6.0


def test_game_model_evaluation_and_promotion_require_evidence():
    metrics = evaluate_game_predictions([
        {"home_win_probability": 0.7, "actual_home_win": 1.0},
        {"home_win_probability": 0.4, "actual_home_win": 0.0},
    ])
    assert metrics["settled_games"] == 2
    assert metrics["brier_score"] < 0.2
    assert promotion_decision(metrics)["promotable"] is False


def test_game_evaluation_uses_newest_rows_for_chronological_holdout():
    rows = [
        {
            "sport": "WNBA",
            "game_start": f"2026-07-{index + 1:02d}T19:00:00Z",
            "home_win_probability": 0.8,
            "actual_home_win": 1.0 if index >= 6 else 0.0,
        }
        for index in range(8)
    ]
    result = chronological_game_evaluation(rows, holdout_fraction=0.25)
    assert result["training_games"] == 6
    assert result["holdout_games"] == 2
    assert result["metrics"]["accuracy"] == 100.0
    assert any(row["dimension"] == "sport" and row["value"] == "WNBA" for row in result["segments"])


def test_saved_slate_groups_champion_and_challenger_by_game():
    generated_at = datetime.now(UTC).isoformat()
    for version in ("game-market-baseline-v1", GAME_CONTEXT_CHALLENGER_VERSION):
        snapshot = predict_game(_features(game_id="grouped-game-test"), model_version=version).snapshot()
        GamePredictionRepository.save(snapshot | {"generated_at": generated_at})
    grouped = [row for row in latest_slate_predictions("WNBA", 100) if row["champion"]["game_id"] == "grouped-game-test"]
    assert len(grouped) == 1
    assert grouped[0]["champion"]["model_version"] == "game-market-baseline-v1"
    assert grouped[0]["challenger"]["model_version"] == GAME_CONTEXT_CHALLENGER_VERSION


def test_game_detail_keeps_latest_snapshot_per_model():
    rows = GamePredictionRepository.latest_for_game("grouped-game-test")
    assert {row["model_version"] for row in rows} >= {"game-market-baseline-v1", GAME_CONTEXT_CHALLENGER_VERSION}
