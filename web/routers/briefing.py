from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

router = APIRouter(tags=["briefing"])


@dataclass
class BriefingDependencies:
    briefing: Callable[[str, str | None, bool, bool], dict]
    new_scan: Callable[[str, str | None, str], dict]
    save_scan: Callable[[dict], dict]
    run_scan: Callable[[str, str | None, str | None, str, dict | None], dict]
    scan_status: Callable[[str, str | None], dict]


_deps_store: list[BriefingDependencies] = []


def configure_briefing_router(dependencies: BriefingDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> BriefingDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Briefing router dependencies have not been configured.")
    return _deps_store[0]


DepsBriefing = Annotated[BriefingDependencies, Depends(get_deps)]


def _sport_filter(sport: str) -> str | None:
    return None if sport == "All Sports" else sport.upper()


@router.get("/api/daily-briefing")
def daily_briefing(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    refresh: bool = False,
    cached_only: bool = False,
    deps: DepsBriefing = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, BriefingDependencies) else get_deps()
    return _deps.briefing(platform, _sport_filter(sport), refresh, cached_only)


@router.post("/api/daily-briefing/scan")
def start_daily_briefing_scan(
    background_tasks: BackgroundTasks,
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    deps: DepsBriefing = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, BriefingDependencies) else get_deps()
    sport_filter = _sport_filter(sport)
    current = (_deps.scan_status(platform, sport_filter) or {}).get("current") or {}
    if current.get("status") in {"scanning_props", "analyzing_games", "building_entries"}:
        return current
    scan = _deps.new_scan(platform, sport_filter, "manual")
    _deps.save_scan(scan)
    background_tasks.add_task(_deps.run_scan, platform, sport_filter, scan["id"], "manual", None)
    return scan


@router.get("/api/daily-briefing/scan-status")
def daily_briefing_scan_status(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    deps: DepsBriefing = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, BriefingDependencies) else get_deps()
    return _deps.scan_status(platform, _sport_filter(sport))
