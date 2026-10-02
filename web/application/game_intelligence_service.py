from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from analytics.game_features import prop_opportunity_context
from analytics.game_model_evaluation import promotion_evidence
from analytics.game_model_registry import (
    GAME_CONTEXT_CHALLENGER_VERSION,
    GAME_HISTORICAL_BASELINE_VERSION,
    GAME_MARKET_CHAMPION_VERSION,
    game_model_registry,
    promotion_decision,
)
from data.providers.espn import fetch_game_times
from repository.repositories.game_prediction_repository import GamePredictionRepository
from services.game_intelligence import _game_on_day, latest_slate_predictions, predict_slate, settle_recent_predictions
from utils.entity_normalization import canonical_matchup_key
from web.schemas.games import GamePropContextPayload


def slate_payload(sport: str, refresh: bool) -> dict:
    game_day = datetime.now(ZoneInfo("America/New_York")).date()
    rows = predict_slate(sport, persist=True, game_day=game_day) if refresh else latest_slate_predictions(sport, 100, game_day=game_day)
    schedule: list[dict] = []
    schedule_status = "available"
    predicted_matchups = {
        canonical_matchup_key((row.get("champion") or row.get("challenger") or row).get("game"))
        for row in rows
    }
    try:
        schedule = [
            row for row in fetch_game_times(sport, game_day)
            if _game_on_day(row.get("game_time"), game_day)
            and canonical_matchup_key(
                f"{row.get('away_team')} @ {row.get('home_team')}"
                if row.get("away_team") and row.get("home_team") else row.get("game")
            ) not in predicted_matchups
        ]
    except (RuntimeError, ValueError, OSError):
        schedule_status = "unavailable"
    return {
        "sport": sport.upper(), "game_day": game_day.isoformat(), "games": rows,
        "schedule": schedule, "schedule_status": schedule_status,
        "registry": game_model_registry(), "guaranteed": False,
    }


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
