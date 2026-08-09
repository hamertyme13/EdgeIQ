from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from web.application.player_service import PlayerLookupError

router = APIRouter(tags=["players"])


@dataclass(frozen=True)
class PlayerDependencies:
    availability: Callable[[str, str, str, str], dict]
    detail: Callable[[str, str, str], dict]
    identity: Callable[[str, str, str], dict]
    research: Callable[[str, str, str, str, float | None], dict]
    line_movement: Callable[[str, str, str], dict]
    hit_rate: Callable[[str, str, float, float | None, int, str | None], dict]


_dependencies: PlayerDependencies | None = None


def configure_player_router(dependencies: PlayerDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> PlayerDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Player research is still starting. Please try again.")
    return _dependencies


@router.get("/api/players/{player_name}/availability")
def player_availability(player_name: str, sport: str = "WNBA", team: str = "", game: str = "") -> dict:
    return _deps().availability(player_name, sport, team, game)


@router.get("/api/players/{player_name}")
def player_detail(player_name: str, platform: str = "Both", sport: str = "All Sports") -> dict:
    try:
        return _deps().detail(player_name, platform, sport)
    except PlayerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/players/{player_name}/identity")
def player_identity(player_name: str, sport: str = "", team: str = "") -> dict:
    try:
        return _deps().identity(player_name, sport, team)
    except PlayerLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/players/{player_name}/research")
def player_research(
    player_name: str,
    stat: str,
    sport: str = "All Sports",
    platform: str = "Both",
    line: float | None = None,
) -> dict:
    return _deps().research(player_name, stat, sport, platform, line)


@router.get("/api/players/{player_name}/line-movement")
def player_line_movement(player_name: str, stat: str, platform: str = "PrizePicks") -> dict:
    return _deps().line_movement(player_name, stat, platform)


@router.get("/api/players/{player_name}/hit-rate")
def player_hit_rate(
    player_name: str,
    stat: str,
    line: float,
    projection: float | None = None,
    trending_count: int = 0,
    sport: str | None = None,
) -> dict:
    return _deps().hit_rate(player_name, stat, line, projection, trending_count, sport)
