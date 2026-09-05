from __future__ import annotations

from analytics.game_features import prop_opportunity_context
from analytics.game_model_evaluation import chronological_game_evaluation, evaluate_game_predictions
from analytics.game_model_registry import game_model_registry, promotion_decision
from repository.repositories.game_prediction_repository import GamePredictionRepository
from services.game_intelligence import latest_slate_predictions, predict_slate, settle_recent_predictions
from web.schemas.games import GamePropContextPayload


def slate_payload(sport: str, refresh: bool) -> dict:
    rows = predict_slate(sport, persist=True) if refresh else latest_slate_predictions(sport, 100)
    return {"sport": sport.upper(), "games": rows, "registry": game_model_registry(), "guaranteed": False}


def prop_context_payload(payload: GamePropContextPayload) -> dict:
    return prop_opportunity_context(payload.sport, payload.stat, payload.team, payload.game_prediction, expected_minutes=payload.expected_minutes, expected_opportunities=payload.expected_opportunities)


def evaluation_payload(model_version: str = "") -> dict:
    all_rows = GamePredictionRepository.latest(limit=5000)
    rows = all_rows
    if model_version:
        rows = [row for row in rows if row.get("model_version") == model_version]
    metrics = evaluate_game_predictions(rows)
    chronological = chronological_game_evaluation(rows)
    metrics["chronological_holdout"] = chronological["holdout_games"] > 0
    by_model = {}
    for version in sorted({str(row.get("model_version") or "") for row in all_rows if row.get("model_version")}):
        version_rows = [row for row in all_rows if row.get("model_version") == version]
        by_model[version] = evaluate_game_predictions(version_rows)
    challenger = by_model.get(model_version) if model_version else None
    market = by_model.get("game-market-baseline-v1")
    if challenger and market and challenger.get("brier_score") is not None and market.get("brier_score") is not None:
        metrics["beats_market_baseline"] = challenger["brier_score"] < market["brier_score"]
    else:
        metrics["beats_market_baseline"] = False
    metrics["beats_historical_baseline"] = False
    return {
        "model_version": model_version or "all",
        "metrics": metrics,
        "chronological": chronological,
        "by_model": by_model,
        "promotion": promotion_decision(metrics),
        "registry": game_model_registry(),
    }


def settlement_payload() -> dict:
    return settle_recent_predictions()


def game_detail_payload(game_id: str) -> dict:
    rows = GamePredictionRepository.latest_for_game(game_id)
    return {"game_id": game_id, "predictions": rows, "registry": game_model_registry(), "guaranteed": False}
