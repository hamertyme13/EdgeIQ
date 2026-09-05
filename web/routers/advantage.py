from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(tags=["advantage"])


@dataclass
class AdvantageDependencies:
    advantage_center: Callable[[str, str | None], dict]


_deps_store: list[AdvantageDependencies] = []


def configure_advantage_router(dependencies: AdvantageDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> AdvantageDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Advantage router dependencies have not been configured.")
    return _deps_store[0]


DepsAdv = Annotated[AdvantageDependencies, Depends(get_deps)]


@router.get("/api/dashboard/advantage-center")
def advantage_center(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    deps: DepsAdv = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, AdvantageDependencies) else get_deps()
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _deps.advantage_center(platform, sport_filter)
