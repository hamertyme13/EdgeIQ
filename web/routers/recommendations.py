from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from web.application.recommendation_service import RecommendationRequestError
from web.schemas import AutoPaperCalibrationPayload

router = APIRouter(tags=["recommendations"])


@dataclass(frozen=True)
class RecommendationDependencies:
    top_props: Callable[[str, str, int], dict]
    trending_props: Callable[[str, str, int], dict]
    confirmed_props: Callable[[str, str, int], dict]
    dashboard_parlay: Callable[[str, str], dict]
    command_center: Callable[[str, str, bool], dict]
    opportunity_feed: Callable[[str, str, float, int, int], dict]
    auto_paper: Callable[[AutoPaperCalibrationPayload], dict]
    start_auto_paper: Callable[[AutoPaperCalibrationPayload], dict]
    paper_calibration_status: Callable[[], dict]
    entry_suggestions: Callable[[str, str, int, set[str]], dict]
    confirmed_suggestions: Callable[[str, str], dict]
    crazy_six: Callable[[str, str], dict]
    optimizer: Callable[..., dict]


_deps_store: list[RecommendationDependencies] = []


def configure_recommendation_router(dependencies: RecommendationDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> RecommendationDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Recommendations are still starting. Please try again.")
    return _deps_store[0]


DepsRec = Annotated[RecommendationDependencies, Depends(get_deps)]


def _request(call: Callable[[], dict]) -> dict:
    try:
        return call()
    except RecommendationRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/props/top")
def top_props(platform: str = "PrizePicks", sport: str = "All Sports", limit: int = 5, deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.top_props(platform, sport, limit)


@router.get("/api/props/trending")
def trending_props(platform: str = "PrizePicks", sport: str = "WNBA", limit: int = 15, deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.trending_props(platform, sport, limit)


@router.get("/api/props/confirmed")
def confirmed_props(platform: str = "PrizePicks", sport: str = "All Sports", limit: int = 20, deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.confirmed_props(platform, sport, limit)


@router.get("/api/dashboard/parlay")
def dashboard_parlay(platform: str = "PrizePicks", sport: str = "All Sports", deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.dashboard_parlay(platform, sport)


@router.get("/api/dashboard/command-center")
def dashboard_command_center(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    refresh: bool = False,
    deps: DepsRec = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.command_center(platform, sport, refresh)


@router.get("/api/market/opportunity-feed")
def opportunity_feed(
    platform: str = "Both",
    sport: str = "All Sports",
    min_ev: float = 0.0,
    limit: int = 12,
    odds: int = -110,
    deps: DepsRec = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.opportunity_feed(platform, sport, min_ev, limit, odds)


@router.post("/api/entries/auto-paper-calibration")
def auto_paper_calibration(payload: AutoPaperCalibrationPayload, deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.auto_paper(payload)


@router.post("/api/entries/auto-paper-calibration/jobs", status_code=202)
def start_auto_paper_calibration(payload: AutoPaperCalibrationPayload, deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.start_auto_paper(payload)


@router.get("/api/entries/paper-calibration-status")
def paper_calibration_status(deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.paper_calibration_status()


@router.get("/api/entries/suggestions")
def entry_suggestions(
    sport: str = "WNBA",
    platform: str = "PrizePicks",
    leg_count: int = 2,
    avoid: str = "",
    deps: DepsRec = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    avoid_prop_keys = {key for key in avoid.split(",") if key}
    return _request(lambda: _deps.entry_suggestions(sport, platform, leg_count, avoid_prop_keys))


@router.get("/api/entries/confirmed-suggestions")
def confirmed_entry_suggestions(sport: str = "WNBA", platform: str = "PrizePicks", deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.confirmed_suggestions(sport, platform)


@router.get("/api/entries/crazy-six")
def crazy_six_suggestion(sport: str = "All Sports", platform: str = "PrizePicks", deps: DepsRec = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _deps.crazy_six(sport, platform)


@router.get("/api/entries/optimizer")
def optimize_entries(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    min_legs: int = 2,
    max_legs: int = 5,
    limit: int = 5,
    min_confidence: float = 0,
    min_edge: float = -999,
    max_same_team: int = 5,
    exclude_correlated: bool = False,
    apply_feedback: bool = True,
    deps: DepsRec = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, RecommendationDependencies) else get_deps()
    return _request(
        lambda: _deps.optimizer(
            platform,
            sport,
            min_legs,
            max_legs,
            limit,
            min_confidence,
            min_edge,
            max_same_team,
            exclude_correlated,
            apply_feedback,
        )
    )
