from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import data.providers.prizepicks as prizepicks
import data.providers.underdog as underdog
from analytics.correlation import detect_correlations
from analytics.entry_recommendation import recommendation as entry_recommendation
from analytics.entry_suggestions import suggest_entries
from analytics.ev import expected_value, sportsbook_probability
from analytics.kelly import breakeven_probability, half_kelly, kelly_fraction, suggested_wager
from analytics.projection import auto_projection
from analytics.prop_metrics import calculate_confidence, calculate_edge
from analytics.risk import calculate_entry_risk
from analytics.recommendation import recommendation as ev_recommendation
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from models.bet import Bet
from models.entry import Entry
from models.platform import Platform
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType
from pydantic import BaseModel, Field
from repository.bet_repository import BetRepository
from repository.database import initialize_database
from repository.repositories.entry_repository import EntryRepository
from services.betting import potential_profit
from services.dashboard import get_dashboard, get_starting_bankroll, set_starting_bankroll


STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="EdgeIQ Web", version="2.0.0-alpha", lifespan=lifespan)
allowed_origins = [
    origin.strip()
    for origin in os.getenv("EDGEIQ_ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


class BankrollPayload(BaseModel):
    amount: float = Field(gt=0)


@app.get("/api/dashboard")
def dashboard() -> dict:
    return get_dashboard()


@app.post("/api/settings/bankroll")
def update_bankroll(payload: BankrollPayload) -> dict:
    set_starting_bankroll(payload.amount)
    return get_dashboard(payload.amount)


@app.get("/api/props/top")
def top_props(
    platform: Literal["PrizePicks", "Underdog", "Both"] = "PrizePicks",
    sport: str = "All Sports",
    limit: int = 25,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    props = _fetch_props(platform, sport_filter)
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return {
        "props": _unique_player_props(props, limit),
        "platform": platform,
        "sport": sport,
    }


class EvPayload(BaseModel):
    odds: int
    probability: float = Field(ge=0, le=100)


@app.post("/api/analysis/ev")
def analyze_ev(payload: EvPayload) -> dict:
    probability_decimal = payload.probability / 100
    sportsbook = sportsbook_probability(payload.odds) * 100
    ev_percent = expected_value(payload.odds, probability_decimal) * 100
    edge = payload.probability - sportsbook
    bankroll = get_starting_bankroll()
    result = ev_recommendation(ev_percent)

    return {
        "sportsbook_probability": round(sportsbook, 2),
        "edge": round(edge, 2),
        "expected_value": round(ev_percent, 2),
        "break_even": round(breakeven_probability(payload.odds) * 100, 2),
        "full_kelly": round(kelly_fraction(payload.odds, probability_decimal) * 100, 2),
        "half_kelly": round(half_kelly(payload.odds, probability_decimal) * 100, 2),
        "suggested_wager": suggested_wager(payload.odds, probability_decimal, bankroll),
        "recommendation": result,
    }


class PropPayload(BaseModel):
    player: str
    team: str = ""
    sport: str
    stat: str
    line: float
    projection: float | None = None
    platform: str = "PrizePicks"
    game: str = ""
    trending_count: int = 0


class EntryPayload(BaseModel):
    platform: str = "PrizePicks"
    props: list[PropPayload]


@app.post("/api/entries/analyze")
def analyze_entry(payload: EntryPayload) -> dict:
    entry = _entry_from_payload(payload)
    return _entry_analysis(entry)


@app.post("/api/entries/place")
def place_entry(payload: EntryPayload) -> dict:
    entry = _entry_from_payload(payload)
    entry_id = EntryRepository.save(entry, status="Pending")
    return {"id": entry_id, "status": "Pending", "analysis": _entry_analysis(entry)}


@app.get("/api/entries/pending")
def pending_entries() -> dict:
    return {"entries": [_serialize_pending(entry) for entry in EntryRepository.pending()]}


class SettlePayload(BaseModel):
    result: Literal["Win", "Loss", "Push"]


@app.post("/api/entries/{entry_id}/settle")
def settle_entry(entry_id: int, payload: SettlePayload) -> dict:
    EntryRepository.settle(entry_id, payload.result)
    return {"id": entry_id, "result": payload.result, "status": "Settled"}


@app.get("/api/entries/suggestions")
def entry_suggestions(
    sport: str = "WNBA",
    platform: Literal["PrizePicks", "Underdog"] = "PrizePicks",
) -> dict:
    platform_model = _platform_from_text(platform)
    raw_props = prizepicks.fetch_projections(limit=1000) if platform_model == Platform.PRIZEPICKS else underdog.fetch_projections()
    suggestions = suggest_entries(raw_props, sport, platform_model)
    return {"suggestions": [_serialize_suggestion(suggestion) for suggestion in suggestions]}


@app.get("/api/bets")
def bets() -> dict:
    return {"bets": [_serialize_bet(bet) for bet in BetRepository().get_all()]}


class BetPayload(BaseModel):
    sport: str
    game: str
    description: str
    odds: int
    wager: float = Field(gt=0)
    result: Literal["Win", "Loss", "Push"]
    platform: str = ""
    stat_type: str = ""
    win_probability: float = 0


@app.post("/api/bets")
def save_bet(payload: BetPayload) -> dict:
    profit = 0.0
    if payload.result == "Win":
        profit = potential_profit(payload.odds, payload.wager)
    elif payload.result == "Loss":
        profit = -payload.wager

    bet = Bet(
        sport=payload.sport,
        game=payload.game,
        description=payload.description,
        odds=payload.odds,
        wager=payload.wager,
        result=payload.result,
        profit=round(profit, 2),
        platform=payload.platform,
        stat_type=payload.stat_type,
        win_probability=payload.win_probability,
    )
    BetRepository().save(bet)
    return {"bet": _serialize_bet(bet), "dashboard": get_dashboard()}


@app.get("/api/performance")
def performance() -> dict:
    stats = get_dashboard()
    return {
        "bankroll_curve": stats.get("bankroll_curve", []),
        "by_sport": stats.get("by_sport", {}),
        "by_stat": stats.get("by_stat", {}),
        "by_platform": stats.get("by_platform", {}),
        "summary": stats,
    }


def _fetch_props(platform: str, sport_filter: str | None) -> list[dict]:
    if platform == "PrizePicks":
        props = prizepicks.fetch_projections(limit=1000)
        for prop in props:
            prop.setdefault("platform", "PrizePicks")
    elif platform == "Underdog":
        props = underdog.fetch_projections()
    else:
        props = prizepicks.fetch_projections(limit=1000) + underdog.fetch_projections()
        for prop in props:
            prop.setdefault("platform", "PrizePicks")

    if sport_filter:
        props = [prop for prop in props if prop.get("league", "").upper() == sport_filter]
    return props


def _unique_player_props(props: list[dict], limit: int) -> list[dict]:
    unique: list[dict] = []
    seen: set[str] = set()
    for prop in props:
        key = prop.get("player", "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(prop)
        if len(unique) == limit:
            break
    return unique


def _entry_from_payload(payload: EntryPayload) -> Entry:
    return Entry(
        platform=_platform_from_text(payload.platform),
        props=[_prop_from_payload(prop, payload.platform) for prop in payload.props],
    )


def _prop_from_payload(payload: PropPayload, entry_platform: str) -> Prop:
    projection = payload.projection
    auto_projected = False
    if projection is None:
        projection = auto_projection(payload.line, payload.trending_count)
        auto_projected = True
    edge = calculate_edge(payload.line, projection)
    return Prop(
        player=Player(name=payload.player, team=payload.team, sport=payload.sport),
        stat=_stat_from_text(payload.stat),
        line=payload.line,
        projection=projection,
        edge=edge,
        confidence=calculate_confidence(edge),
        platform=_platform_from_text(payload.platform or entry_platform),
        game=payload.game,
        needs_projection=False,
        auto_projected=auto_projected,
        trending_count=payload.trending_count,
    )


def _entry_analysis(entry: Entry) -> dict:
    result = entry_recommendation(entry)
    risk = calculate_entry_risk(entry.props)
    warnings = detect_correlations(entry)
    return {
        "entry": _serialize_entry(entry),
        "recommendation": result,
        "risk": {
            "level": risk.risk.value,
            "average_confidence": round(risk.average_confidence, 2),
            "average_edge": round(risk.average_edge, 2),
            "prop_count": risk.prop_count,
        },
        "warnings": warnings,
    }


def _serialize_entry(entry: Entry) -> dict:
    return {
        "platform": entry.platform.value,
        "average_confidence": round(entry.average_confidence, 2),
        "average_edge": round(entry.average_edge, 2),
        "props": [_serialize_prop(prop) for prop in entry.props],
    }


def _serialize_prop(prop: Prop) -> dict:
    return {
        "player": prop.player.name,
        "team": prop.player.team,
        "sport": prop.player.sport,
        "stat": prop.stat.value,
        "line": prop.line,
        "projection": prop.projection,
        "edge": round(prop.edge, 2),
        "confidence": round(prop.confidence, 2),
        "platform": prop.platform.value,
        "game": prop.game,
        "auto_projected": prop.auto_projected,
        "trending_count": prop.trending_count,
    }


def _serialize_suggestion(suggestion) -> dict:
    return {
        "rank": suggestion.rank,
        "score": suggestion.score,
        "grade": suggestion.grade,
        "action": suggestion.action,
        "warnings": suggestion.warnings,
        "entry": _serialize_entry(suggestion.entry),
    }


def _serialize_pending(entry: dict) -> dict:
    return {
        **entry,
        "placed_at": entry["placed_at"].isoformat() if entry.get("placed_at") else "",
    }


def _serialize_bet(bet: Bet) -> dict:
    return {
        "sport": bet.sport,
        "game": bet.game,
        "description": bet.description,
        "odds": bet.odds,
        "wager": bet.wager,
        "result": bet.result,
        "profit": bet.profit,
        "platform": bet.platform,
        "stat_type": bet.stat_type,
        "win_probability": bet.win_probability,
    }


def _platform_from_text(value: str) -> Platform:
    for platform in Platform:
        if platform.value.lower() == (value or "").lower():
            return platform
    return Platform.PRIZEPICKS


def _stat_from_text(value: str) -> StatType:
    normalized = (value or "").lower()
    for stat in StatType:
        if stat.value.lower() == normalized or stat.value.lower() in normalized:
            return stat
    if "point" in normalized:
        return StatType.POINTS
    if "rebound" in normalized:
        return StatType.REBOUNDS
    if "assist" in normalized:
        return StatType.ASSISTS
    if "pra" in normalized:
        return StatType.PRA
    return StatType.POINTS
