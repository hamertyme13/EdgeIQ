from fastapi import APIRouter, Query

from services.background_jobs import background_jobs
from services.game_intelligence import predict_slate
from web.application.game_intelligence_service import (
    evaluation_payload,
    game_detail_payload,
    prop_context_payload,
    settlement_payload,
    slate_payload,
)
from web.schemas.games import GamePropContextPayload

router = APIRouter(prefix="/api/game-intelligence", tags=["game-intelligence"])


@router.get("/slate")
def game_slate(sport: str = "WNBA", refresh: bool = False) -> dict:
    return slate_payload(sport, refresh)


@router.post("/refresh")
def refresh_game_slate(sport: str = "WNBA") -> dict:
    normalized_sport = sport.strip().upper() or "WNBA"

    def task(context) -> dict:
        context.update(10, f"Loading {normalized_sport} market evidence...")
        games = predict_slate(normalized_sport, persist=True)
        context.update(90, "Saving immutable game predictions...")
        return {"message": f"{len(games)} {normalized_sport} games refreshed.", "sport": normalized_sport, "count": len(games)}

    return background_jobs.submit(
        "game_prediction_refresh",
        task,
        dedupe_key=f"game-prediction-refresh:{normalized_sport}",
        label=f"Refresh {normalized_sport} game predictions",
    )


@router.get("/evaluation")
def game_evaluation(model_version: str = Query(default="")) -> dict:
    return evaluation_payload(model_version)


@router.get("/games/{game_id}")
def game_detail(game_id: str) -> dict:
    return game_detail_payload(game_id)


@router.post("/prop-context")
def game_prop_context(payload: GamePropContextPayload) -> dict:
    return prop_context_payload(payload)


@router.post("/settle")
def settle_games() -> dict:
    return settlement_payload()
