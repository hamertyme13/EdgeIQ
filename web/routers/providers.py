from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(tags=["providers"])


@dataclass(frozen=True)
class ProviderDependencies:
    data_health: Callable[[], dict]
    sleeper_status: Callable[[], dict]
    verify_odds: Callable[[], dict]


_deps_store: list[ProviderDependencies] = []


def configure_provider_router(dependencies: ProviderDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> ProviderDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Provider status is still starting. Please try again.")
    return _deps_store[0]


DepsProvider = Annotated[ProviderDependencies, Depends(get_deps)]


@router.get("/api/data-health")
def data_health(deps: DepsProvider = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ProviderDependencies) else get_deps()
    return _deps.data_health()


@router.get("/api/providers/sleeper/status")
def sleeper_status(deps: DepsProvider = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ProviderDependencies) else get_deps()
    return _deps.sleeper_status()


@router.post("/api/providers/odds/verify")
def verify_odds(deps: DepsProvider = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ProviderDependencies) else get_deps()
    return _deps.verify_odds()
