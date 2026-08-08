from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter

router = APIRouter(tags=["advantage"])


@dataclass
class AdvantageDependencies:
    advantage_center: Callable[[str, str | None], dict]


_dependencies: AdvantageDependencies | None = None


def configure_advantage_router(dependencies: AdvantageDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> AdvantageDependencies:
    if _dependencies is None:
        raise RuntimeError("Advantage router dependencies have not been configured.")
    return _dependencies


@router.get("/api/dashboard/advantage-center")
def advantage_center(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _deps().advantage_center(platform, sport_filter)
