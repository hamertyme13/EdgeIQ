from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from repository.repositories.player_identity_repository import PlayerIdentityRepository
from web.application.player_service import PlayerLookupError
from web.application.season_history_service import season_history_status, start_season_history_sync

router = APIRouter(tags=["players"])


@dataclass(frozen=True)
class PlayerDependencies:
    availability: Callable[[str, str, str, str], dict]
    detail: Callable[[str, str, str], dict]
    identity: Callable[[str, str, str], dict]
    research: Callable[[str, str, str, str, float | None], dict]
    research_evidence: Callable[[str, str, str, str, str, bool], dict]
    line_movement: Callable[[str, str, str], dict]
    hit_rate: Callable[[str, str, float, float | None, int, str | None], dict]


_deps_store: list[PlayerDependencies] = []


def configure_player_router(dependencies: PlayerDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> PlayerDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Player research is still starting. Please try again.")
    return _deps_store[0]


DepsPlayer = Annotated[PlayerDependencies, Depends(get_deps)]


@router.get("/api/players/directory")
def player_directory(sport: str, query: str = "", limit: int = 100) -> dict:
    sport_key = str(sport or "").strip().upper()
    if not sport_key:
        raise HTTPException(status_code=400, detail="Choose a sport before searching for a player.")
    players = PlayerIdentityRepository.search(sport_key, query, limit)
    return {
        "sport": sport_key,
        "query": query.strip(),
        "players": players,
        "count": len(players),
    }


@router.get("/api/players/{player_name}/availability")
def player_availability(player_name: str, sport: str = "WNBA", team: str = "", game: str = "", deps: DepsPlayer = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PlayerDependencies) else get_deps()
    return _deps.availability(player_name, sport, team, game)


@router.get("/api/players/{player_name}")
def player_detail(player_name: str, platform: str = "Both", sport: str = "All Sports", deps: DepsPlayer = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PlayerDependencies) else get_deps()
    try:
        return _deps.detail(player_name, platform, sport)
    except PlayerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/players/{player_name}/identity")
def player_identity(player_name: str, sport: str = "", team: str = "", deps: DepsPlayer = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PlayerDependencies) else get_deps()
    try:
        return _deps.identity(player_name, sport, team)
    except PlayerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/players/{player_name}/research")
def player_research(
    player_name: str,
    stat: str,
    sport: str = "All Sports",
    platform: str = "Both",
    line: float | None = None,
    deps: DepsPlayer = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, PlayerDependencies) else get_deps()
    return _deps.research(player_name, stat, sport, platform, line)


@router.post("/api/players/season-history/sync")
def sync_season_history(sport: str) -> dict:
    return start_season_history_sync(sport)


@router.get("/api/players/season-history/status")
def get_season_history_status() -> dict:
    return season_history_status()


@router.get("/api/research/evidence")
def research_evidence(
    player: str,
    stat: str = "",
    sport: str = "",
    platform: str = "Both",
    game: str = "",
    include_expired: bool = False,
    deps: DepsPlayer = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, PlayerDependencies) else get_deps()
    return _deps.research_evidence(player, stat, sport, platform, game, include_expired)


@router.get("/api/players/{player_name}/line-movement")
def player_line_movement(player_name: str, stat: str, platform: str = "PrizePicks", deps: DepsPlayer = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PlayerDependencies) else get_deps()
    return _deps.line_movement(player_name, stat, platform)


@router.get("/api/players/{player_name}/hit-rate")
def player_hit_rate(
    player_name: str,
    stat: str,
    line: float,
    projection: float | None = None,
    trending_count: int = 0,
    sport: str | None = None,
    deps: DepsPlayer = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, PlayerDependencies) else get_deps()
    return _deps.hit_rate(player_name, stat, line, projection, trending_count, sport)
