from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from web.schemas import BetPayload

router = APIRouter(tags=["portfolio"])


@dataclass(frozen=True)
class PortfolioDependencies:
    dashboard: Callable[[], dict]
    personal_profile: Callable[[], dict]
    bets: Callable[[int, int], dict]
    save_bet: Callable[[BetPayload], dict]
    intelligence: Callable[[], dict]
    refresh_market: Callable[[], dict]


_deps_store: list[PortfolioDependencies] = []


def configure_portfolio_router(dependencies: PortfolioDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> PortfolioDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Portfolio tracking is still starting. Please try again.")
    return _deps_store[0]


DepsPortfolio = Annotated[PortfolioDependencies, Depends(get_deps)]


@router.get("/api/dashboard")
def dashboard(deps: DepsPortfolio = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PortfolioDependencies) else get_deps()
    return _deps.dashboard()


@router.get("/api/analytics/personal-profile")
def personal_profile(deps: DepsPortfolio = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PortfolioDependencies) else get_deps()
    return _deps.personal_profile()


@router.get("/api/bets")
def bets(limit: int = 100, entry_limit: int = 50, deps: DepsPortfolio = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PortfolioDependencies) else get_deps()
    return _deps.bets(limit, entry_limit)


@router.post("/api/bets")
def save_bet(payload: BetPayload, deps: DepsPortfolio = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PortfolioDependencies) else get_deps()
    return _deps.save_bet(payload)


@router.get("/api/portfolio/intelligence")
def portfolio_intelligence(deps: DepsPortfolio = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PortfolioDependencies) else get_deps()
    return _deps.intelligence()


@router.post("/api/portfolio/refresh-market-data")
def refresh_portfolio_market_data(deps: DepsPortfolio = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, PortfolioDependencies) else get_deps()
    return _deps.refresh_market()
