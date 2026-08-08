from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from web.schemas import BetPayload

router = APIRouter(tags=["portfolio"])


@dataclass(frozen=True)
class PortfolioDependencies:
    dashboard: Callable[[], dict]
    personal_profile: Callable[[], dict]
    bets: Callable[[int, int], dict]
    save_bet: Callable[[BetPayload], dict]


_dependencies: PortfolioDependencies | None = None


def configure_portfolio_router(dependencies: PortfolioDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> PortfolioDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Portfolio tracking is still starting. Please try again.")
    return _dependencies


@router.get("/api/dashboard")
def dashboard() -> dict:
    return _deps().dashboard()


@router.get("/api/analytics/personal-profile")
def personal_profile() -> dict:
    return _deps().personal_profile()


@router.get("/api/bets")
def bets(limit: int = 100, entry_limit: int = 50) -> dict:
    return _deps().bets(limit, entry_limit)


@router.post("/api/bets")
def save_bet(payload: BetPayload) -> dict:
    return _deps().save_bet(payload)
