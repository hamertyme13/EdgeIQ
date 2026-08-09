from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["providers"])


@dataclass(frozen=True)
class ProviderDependencies:
    data_health: Callable[[], dict]
    sleeper_status: Callable[[], dict]
    verify_odds: Callable[[], dict]


_dependencies: ProviderDependencies | None = None


def configure_provider_router(dependencies: ProviderDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> ProviderDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Provider status is still starting. Please try again.")
    return _dependencies


@router.get("/api/data-health")
def data_health() -> dict:
    return _deps().data_health()


@router.get("/api/providers/sleeper/status")
def sleeper_status() -> dict:
    return _deps().sleeper_status()


@router.post("/api/providers/odds/verify")
def verify_odds() -> dict:
    return _deps().verify_odds()
