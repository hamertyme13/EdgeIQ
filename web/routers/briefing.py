from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks

router = APIRouter(tags=["briefing"])


@dataclass
class BriefingDependencies:
    briefing: Callable[[str, str | None, bool, bool], dict]
    new_scan: Callable[[str, str | None, str], dict]
    save_scan: Callable[[dict], dict]
    run_scan: Callable[[str, str | None, str | None, str, dict | None], dict]
    scan_status: Callable[[str, str | None], dict]


_dependencies: BriefingDependencies | None = None


def configure_briefing_router(dependencies: BriefingDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> BriefingDependencies:
    if _dependencies is None:
        raise RuntimeError("Briefing router dependencies have not been configured.")
    return _dependencies


def _sport_filter(sport: str) -> str | None:
    return None if sport == "All Sports" else sport.upper()


@router.get("/api/daily-briefing")
def daily_briefing(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    refresh: bool = False,
    cached_only: bool = False,
) -> dict:
    return _deps().briefing(platform, _sport_filter(sport), refresh, cached_only)


@router.post("/api/daily-briefing/scan")
def start_daily_briefing_scan(
    background_tasks: BackgroundTasks,
    platform: str = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    sport_filter = _sport_filter(sport)
    dependencies = _deps()
    scan = dependencies.new_scan(platform, sport_filter, "manual")
    dependencies.save_scan(scan)
    background_tasks.add_task(dependencies.run_scan, platform, sport_filter, scan["id"], "manual", None)
    return scan


@router.get("/api/daily-briefing/scan-status")
def daily_briefing_scan_status(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    return _deps().scan_status(platform, _sport_filter(sport))
