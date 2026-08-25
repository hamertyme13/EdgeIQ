from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from services import odds as sportsbook_odds
from web.schemas import BoostAnalysisPayload, HedgeCalculatorPayload, MiddleCalculatorPayload

router = APIRouter(prefix="/api/market", tags=["market"])


@dataclass(frozen=True)
class MarketDependencies:
    line_shop: Callable[..., dict]
    sharp_consensus: Callable[..., dict]
    hedge_calculator: Callable[[HedgeCalculatorPayload], dict]
    middle_calculator: Callable[[MiddleCalculatorPayload], dict]
    boost_analysis: Callable[[BoostAnalysisPayload], dict]
    ev_scanner: Callable[..., list[dict]]
    timing_alerts: Callable[..., list[dict]]
    clv_report: Callable[[], dict]


_deps_store: list[MarketDependencies] = []


def configure_market_router(dependencies: MarketDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> MarketDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Market analysis is still starting. Please try again.")
    return _deps_store[0]


DepsMark = Annotated[MarketDependencies, Depends(get_deps)]


@router.get("/line-shop")
def line_shop(
    player: str,
    stat: str,
    sport: str = "All Sports",
    platform: str = "Both",
    over_odds: int | None = None,
    under_odds: int | None = None,
    deps: DepsMark = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, MarketDependencies) else get_deps()
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _deps.line_shop(player, stat, sport_filter, platform, over_odds, under_odds)


@router.get("/sharp-consensus")
def sharp_consensus(
    player: str,
    stat: str,
    sport: str = "All Sports",
    platform: str = "Both",
    over_odds: int | None = None,
    under_odds: int | None = None,
    deps: DepsMark = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, MarketDependencies) else get_deps()
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _deps.sharp_consensus(player, stat, sport_filter, platform, over_odds, under_odds)


@router.get("/player-odds")
def player_market_odds(
    player: str,
    stat: str,
    sport: str,
    game: str,
    line: float,
    direction: str = "Over",
    team: str = "",
) -> dict:
    return sportsbook_odds.get_player_prop_consensus(
        player,
        stat,
        sport,
        game,
        line,
        direction,
        team,
    )


@router.post("/hedge-calculator")
def hedge_calculator(payload: HedgeCalculatorPayload, deps: DepsMark = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, MarketDependencies) else get_deps()
    return _deps.hedge_calculator(payload)


@router.post("/middle-calculator")
def middle_calculator(payload: MiddleCalculatorPayload, deps: DepsMark = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, MarketDependencies) else get_deps()
    return _deps.middle_calculator(payload)


@router.post("/boost-analysis")
def boost_analysis(payload: BoostAnalysisPayload, deps: DepsMark = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, MarketDependencies) else get_deps()
    return _deps.boost_analysis(payload)


@router.get("/ev-scanner")
def ev_scanner(
    platform: str = "Both",
    sport: str = "All Sports",
    min_ev: float = 0.0,
    limit: int = 25,
    odds: int = -110,
    deps: DepsMark = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, MarketDependencies) else get_deps()
    sport_filter = None if sport == "All Sports" else sport.upper()
    rows = _deps.ev_scanner(platform, sport_filter, min_ev, limit, odds)
    return {
        "props": rows,
        "platform": platform,
        "sport": sport,
        "min_ev": min_ev,
        "odds": odds,
        "count": len(rows),
    }


@router.get("/timing-alerts")
def market_timing_alerts(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    limit: int = 8,
    odds: int = -110,
    min_confidence: float = 0.0,
    min_ev: float = -25.0,
    alert_type: str = "All",
    hide_outliers: bool = False,
    deps: DepsMark = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, MarketDependencies) else get_deps()
    sport_filter = None if sport == "All Sports" else sport.upper()
    rows = _deps.timing_alerts(
        platform,
        sport_filter,
        limit,
        odds,
        min_confidence,
        min_ev,
        alert_type,
        hide_outliers,
    )
    return {
        "alerts": rows,
        "platform": platform,
        "sport": sport,
        "count": len(rows),
    }


@router.get("/clv")
def clv_report(deps: DepsMark = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, MarketDependencies) else get_deps()
    return _deps.clv_report()
