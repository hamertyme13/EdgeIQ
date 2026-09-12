from __future__ import annotations

from analytics.game_features import prop_opportunity_context
from analytics.game_model_evaluation import promotion_evidence
from analytics.game_model_registry import (
    GAME_CONTEXT_CHALLENGER_VERSION,
    GAME_HISTORICAL_BASELINE_VERSION,
    GAME_MARKET_CHAMPION_VERSION,
    game_model_registry,
    promotion_decision,
)
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
    candidate_version = model_version or GAME_CONTEXT_CHALLENGER_VERSION
    evidence = promotion_evidence(all_rows, candidate_version)
    metrics = evidence["metrics"]
    comparisons = {
        label: {
            "candidate": metrics, "baseline": evidence["by_model"][version],
            "holdout_games": evidence["holdout_games"],
            "beats_baseline": metrics[f"beats_{label}_baseline"],
        }
        for label, version in (("market", GAME_MARKET_CHAMPION_VERSION), ("historical", GAME_HISTORICAL_BASELINE_VERSION))
    }
    return {
        "model_version": candidate_version,
        "metrics": metrics,
        "chronological": evidence | {"segments": []},
        "by_model": evidence["by_model"],
        "baseline_comparisons": comparisons,
        "promotion_evidence": evidence,
        "promotion": promotion_decision(evidence["metrics"]),
        "registry": game_model_registry(),
    }


def settlement_payload() -> dict:
    return settle_recent_predictions()


def game_detail_payload(game_id: str) -> dict:
    rows = GamePredictionRepository.latest_for_game(game_id)
    return {"game_id": game_id, "predictions": rows, "registry": game_model_registry(), "guaranteed": False}
