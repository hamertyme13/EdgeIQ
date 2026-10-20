from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from web.schemas import (
    AiEntryReviewPayload,
    CopilotQueryPayload,
    EvPayload,
    ModelEvaluationPayload,
    ParlayChatPayload,
    ProjectionAssistPayload,
    RecommendationExplainPayload,
)

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
    copilot_query: Callable[..., dict]
    explain_recommendation: Callable[[RecommendationExplainPayload], dict]
    evaluate_model: Callable[[ModelEvaluationPayload], dict]


_deps_store: list[IntelligenceDependencies] = []


def configure_intelligence_router(dependencies: IntelligenceDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> IntelligenceDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Game intelligence is still starting. Please try again.")
    return _deps_store[0]


DepsIntel = Annotated[IntelligenceDependencies, Depends(get_deps)]


@router.post("/api/ai/parlay-chat")
def ai_parlay_chat(payload: ParlayChatPayload, deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.parlay_chat(payload)


@router.get("/api/ai/status")
def ai_status(deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.ai_status()


@router.post("/api/ai/entry-review")
def ai_entry_review(payload: AiEntryReviewPayload, deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.entry_review(payload)


@router.post("/api/ai/copilot")
def ai_copilot(payload: CopilotQueryPayload, deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.copilot_query(payload)


@router.post("/api/ai/copilot/stream")
async def ai_copilot_stream(payload: CopilotQueryPayload, deps: DepsIntel = None) -> StreamingResponse:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()

    async def events():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

        def send(event: str, data: dict) -> None:
            if not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, (event, data))

        def progress(stage: str, label: str) -> None:
            send("status", {"stage": stage, "label": label})

        def run_query() -> None:
            try:
                result = _deps.copilot_query(payload, progress)
                send("answer", result)
            except Exception:
                send("error", {
                    "message": "EdgeIQ could not finish this research. Please try again shortly.",
                })
            finally:
                send("done", {})

        task = asyncio.create_task(asyncio.to_thread(run_query))
        try:
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": waiting\n\n"
                    continue
                yield f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
                if event == "done":
                    break
        finally:
            if task.done():
                await task

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/api/ai/explain-recommendation")
def explain_recommendation(payload: RecommendationExplainPayload, deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.explain_recommendation(payload)


@router.post("/api/ai/evaluate-model")
def evaluate_local_model(payload: ModelEvaluationPayload, deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.evaluate_model(payload)


@router.get("/api/games/trending")
def trending_games(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    limit: int = 8,
    deps: DepsIntel = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.trending_games(platform, sport, limit)


@router.get("/api/games/context")
def game_context(game: str, sport: str = "All Sports", platform: str = "Both", deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.game_context(game, sport, platform)


@router.post("/api/analysis/ev")
def analyze_ev(payload: EvPayload, deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.ev_analysis(payload)


@router.post("/api/analysis/projection-assist")
def projection_assist(payload: ProjectionAssistPayload, deps: DepsIntel = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, IntelligenceDependencies) else get_deps()
    return _deps.projection_assist(payload)
