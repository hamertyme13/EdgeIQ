from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from web.schemas import AiEntryReviewPayload, EvPayload, ParlayChatPayload, ProjectionAssistPayload

router = APIRouter(tags=["intelligence"])


@dataclass(frozen=True)
class IntelligenceDependencies:
    parlay_chat: Callable[[ParlayChatPayload], dict]
    ai_status: Callable[[], dict]
    entry_review: Callable[[AiEntryReviewPayload], dict]
    trending_games: Callable[[str, str, int], dict]
    game_context: Callable[[str, str, str], dict]
    ev_analysis: Callable[[EvPayload], dict]
    projection_assist: Callable[[ProjectionAssistPayload], dict]


_dependencies: IntelligenceDependencies | None = None


def configure_intelligence_router(dependencies: IntelligenceDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> IntelligenceDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Game intelligence is still starting. Please try again.")
    return _dependencies


@router.post("/api/ai/parlay-chat")
def ai_parlay_chat(payload: ParlayChatPayload) -> dict:
    return _deps().parlay_chat(payload)


@router.get("/api/ai/status")
def ai_status() -> dict:
    return _deps().ai_status()


@router.post("/api/ai/entry-review")
def ai_entry_review(payload: AiEntryReviewPayload) -> dict:
    return _deps().entry_review(payload)


@router.get("/api/games/trending")
def trending_games(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    limit: int = 8,
) -> dict:
    return _deps().trending_games(platform, sport, limit)


@router.get("/api/games/context")
def game_context(game: str, sport: str = "All Sports", platform: str = "Both") -> dict:
    return _deps().game_context(game, sport, platform)


@router.post("/api/analysis/ev")
def analyze_ev(payload: EvPayload) -> dict:
    return _deps().ev_analysis(payload)


@router.post("/api/analysis/projection-assist")
def projection_assist(payload: ProjectionAssistPayload) -> dict:
    return _deps().projection_assist(payload)
