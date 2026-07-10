from __future__ import annotations

import os
import csv
import json
import base64
from contextlib import asynccontextmanager
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Literal

import data.providers.prizepicks as prizepicks
import data.providers.underdog as underdog
import data.providers.sleeper as sleeper
import data.providers.chalkboard as chalkboard
import data.providers.betr as betr
import data.providers.sportsdataio as sportsdataio
import data.providers.balldontlie as balldontlie
import data.providers.newsapi as newsapi
import data.providers.openweather as openweather
from data.providers.generic_props import normalize_props
from data.providers.espn import refresh_final_stats_for_entries
import requests
from analytics.backtesting import backtest_summary
from analytics.hit_rate import estimate_hit_rate
from analytics.correlation import detect_correlations
from analytics.entry_recommendation import recommendation as entry_recommendation
from analytics.entry_suggestions import suggest_entries
from analytics.ev import expected_value, sportsbook_probability
from analytics.kelly import breakeven_probability, half_kelly, kelly_fraction, suggested_wager
from analytics.projection import auto_projection
from analytics.prop_metrics import calculate_confidence, calculate_edge
from analytics.risk import calculate_entry_risk
from analytics.recommendation import recommendation as ev_recommendation
from analytics.defense_vs_position import analyze_matchup
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
from repository.repositories.bankroll_transaction_repository import BankrollTransactionRepository
from repository.database import initialize_database
from repository.repositories.entry_repository import EntryRepository
from repository.repositories.final_stats_repository import FinalStatsRepository
from repository.repositories.line_history_repository import LineHistoryRepository
from repository.repositories.settings_repository import SettingsRepository
from data.providers.final_stats import find_actual_stat, find_final_stat, import_final_stats
from data.providers.injury_feed import fetch_injuries, is_injured
from services.betting import potential_profit
from services.dashboard import get_dashboard, get_starting_bankroll, set_starting_bankroll


STATIC_DIR = Path(__file__).parent / "static"
SUPPORTED_SPORTS = (
    "WNBA",
    "NBA",
    "NFL",
    "MLB",
    "NHL",
    "NCAAF",
    "NCAAM",
    "NCAAW",
    "MLS",
    "EPL",
    "UCL",
    "TENNIS",
    "PGA",
    "MMA",
    "NASCAR",
)
PROP_PLATFORMS = ("PrizePicks", "Underdog", "Sleeper", "Chalkboard", "Betr", "Ball Don't Lie")
PLATFORM_FILTERS = (*PROP_PLATFORMS, "Both")
SPORT_ALIASES = {
    "ALL SPORTS": None,
    "WNBA": "WNBA",
    "NBA": "NBA",
    "NFL": "NFL",
    "MLB": "MLB",
    "NHL": "NHL",
    "HOCKEY": "NHL",
    "COLLEGE FOOTBALL": "NCAAF",
    "NCAAF": "NCAAF",
    "CFB": "NCAAF",
    "COLLEGE BASKETBALL": "NCAAM",
    "NCAAM": "NCAAM",
    "CBB": "NCAAM",
    "NCAAW": "NCAAW",
    "WOMENS COLLEGE BASKETBALL": "NCAAW",
    "WOMEN'S COLLEGE BASKETBALL": "NCAAW",
    "MLS": "MLS",
    "EPL": "EPL",
    "PREMIER LEAGUE": "EPL",
    "UCL": "UCL",
    "CHAMPIONS LEAGUE": "UCL",
    "SOCCER": "MLS",
    "TENNIS": "TENNIS",
    "ATP": "TENNIS",
    "WTA": "TENNIS",
    "PGA": "PGA",
    "GOLF": "PGA",
    "MMA": "MMA",
    "UFC": "MMA",
    "NASCAR": "NASCAR",
}


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


class BankrollTransactionPayload(BaseModel):
    transaction_type: Literal["Deposit", "Withdrawal"]
    amount: float = Field(gt=0)
    note: str = ""


class DnpSettingPayload(BaseModel):
    mode: Literal["reduce", "refund", "ignore"] = "reduce"


class FinalStatsPayload(BaseModel):
    payload: str
    source: str = "manual"


class BettingHistoryPayload(BaseModel):
    payload: str
    source: str = "manual"


class ProjectionAssistPayload(BaseModel):
    player: str
    sport: str = "WNBA"
    stat: str
    line: float
    projection: float | None = None
    trending_count: int = 0


class ParlayChatPayload(BaseModel):
    message: str = "you need a parlay?"
    platform: str = "PrizePicks"
    sport: str = "All Sports"


class UploadAnalyzePayload(BaseModel):
    file_name: str
    content_base64: str
    mime_type: str = ""
    target: Literal["entry", "props", "final_stats", "bet_history"] = "entry"
    source: str = "upload"


@app.get("/api/dashboard")
def dashboard() -> dict:
    return get_dashboard()


@app.post("/api/settings/bankroll")
def update_bankroll(payload: BankrollPayload) -> dict:
    set_starting_bankroll(payload.amount)
    return get_dashboard(payload.amount)


@app.get("/api/bankroll/transactions")
def bankroll_transactions() -> dict:
    return {
        "summary": BankrollTransactionRepository.summary(),
        "transactions": BankrollTransactionRepository.all(),
        "dashboard": get_dashboard(),
    }


@app.post("/api/bankroll/transactions")
def save_bankroll_transaction(payload: BankrollTransactionPayload) -> dict:
    transaction = BankrollTransactionRepository.save(
        payload.transaction_type,
        payload.amount,
        payload.note,
    )
    return {
        "transaction": transaction,
        "summary": BankrollTransactionRepository.summary(),
        "dashboard": get_dashboard(),
    }


@app.get("/api/settings/dnp")
def dnp_setting() -> dict:
    return {"mode": _dnp_mode()}


@app.post("/api/settings/dnp")
def update_dnp_setting(payload: DnpSettingPayload) -> dict:
    SettingsRepository.set("dnp_handling", payload.mode)
    return {"mode": payload.mode}


@app.get("/api/props/top")
def top_props(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    limit: int = 5,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    props = _fetch_props(platform, sport_filter)
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return {
        "props": _top_props_by_sport(props, limit, sport_filter),
        "platform": platform,
        "sport": sport,
        "per_sport_limit": limit,
    }


@app.get("/api/dashboard/parlay")
def dashboard_parlay(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    suggestion = _recommended_parlay(platform, sport_filter)
    return {
        "suggestion": _serialize_suggestion(suggestion) if suggestion else None,
        "platform": platform,
        "sport": sport,
    }


@app.get("/api/dashboard/command-center")
def dashboard_command_center(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _command_center_payload(platform, sport_filter)


@app.post("/api/ai/parlay-chat")
def ai_parlay_chat(payload: ParlayChatPayload) -> dict:
    request = _parse_parlay_request(payload.message, payload.sport)
    suggestions = _optimized_entries(
        payload.platform,
        request["sport"],
        min_legs=request["leg_count"],
        max_legs=request["leg_count"],
        limit=5,
        min_confidence=0,
        min_edge=-999,
        max_same_team=1,
        exclude_correlated=True,
        apply_feedback=True,
    )
    if not suggestions:
        suggestions = _optimized_entries(
            payload.platform,
            request["sport"],
            min_legs=request["leg_count"],
            max_legs=request["leg_count"],
            limit=5,
            min_confidence=0,
            min_edge=-999,
            max_same_team=5,
            exclude_correlated=False,
            apply_feedback=True,
        )
    serialized = [_serialize_suggestion(suggestion) for suggestion in suggestions]
    fallback = _fallback_parlay_chat(serialized, request)
    ai_text, ai_error = _openai_parlay_response(payload.message, serialized)
    return {
        "message": ai_text or fallback,
        "suggestion": serialized[0] if serialized else None,
        "candidates": serialized,
        "ai_enabled": ai_text is not None,
        "model": _openai_model() if ai_text else "rules-fallback",
        "ai_error": ai_error,
        "request": request,
    }


@app.post("/api/uploads/analyze")
def analyze_uploaded_file(payload: UploadAnalyzePayload) -> dict:
    raw = _decode_uploaded_bytes(payload.content_base64)
    if _is_image_upload(payload):
        return _analyze_uploaded_image(payload, raw)
    return _analyze_uploaded_text_file(payload, raw)


@app.get("/api/ai/status")
def ai_status() -> dict:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return {
        "configured": bool(key),
        "key_format_ok": key.startswith("sk-"),
        "model": _openai_model(),
        "vision_model": _openai_vision_model(),
        "note": (
            "OpenAI key is present and has the expected prefix."
            if key.startswith("sk-")
            else "OpenAI key is missing or does not look like a standard OpenAI API key."
        ),
    }


@app.post("/api/ai/entry-review")
def ai_entry_review(payload: AiEntryReviewPayload) -> dict:
    entry = _entry_from_payload(payload)
    analysis = _entry_analysis(entry)
    fallback = _fallback_entry_review(analysis)
    ai_text, ai_error = _openai_entry_review(payload.question, analysis)
    return {
        "review": ai_text or fallback,
        "analysis": analysis,
        "ai_enabled": ai_text is not None,
        "model": _openai_model() if ai_text else "rules-fallback",
        "ai_error": ai_error,
    }


@app.get("/api/games/trending")
def trending_games(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    limit: int = 8,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    props = _fetch_props(platform, sport_filter)
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    ranked_props = _top_props_by_sport(props, 5, sport_filter)
    games = _trending_games_payload(props, ranked_props, limit)
    return {
        "games": games,
        "platform": platform,
        "sport": sport,
        "ranked_player_count": len({prop.get("player", "") for prop in ranked_props}),
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


@app.post("/api/analysis/projection-assist")
def projection_assist(payload: ProjectionAssistPayload) -> dict:
    projection = payload.projection
    if projection is None:
        projection = auto_projection(payload.line, payload.trending_count)
    hit_rate = estimate_hit_rate(
        payload.player,
        payload.stat,
        payload.line,
        projection,
        payload.trending_count,
        payload.sport,
    )
    edge = calculate_edge(payload.line, projection)
    confidence = calculate_confidence(edge)
    grade = "A" if confidence >= 70 else "B" if confidence >= 60 else "C" if confidence >= 52 else "D"
    return {
        "player": payload.player,
        "sport": payload.sport,
        "stat": payload.stat,
        "line": payload.line,
        "projection": round(projection, 2),
        "edge": round(edge, 2),
        "confidence": round(confidence, 2),
        "estimated_hit_rate": hit_rate.estimated_hit_rate,
        "grade": grade,
        "source": hit_rate.source,
        "recommendation": "Consider" if confidence >= 60 and hit_rate.estimated_hit_rate >= 55 else "Watchlist",
        "reason": (
            f"Projection model sees {edge:+.2f} edge with {hit_rate.source} hit-rate context. "
            "Past betting history improves this once imported because calibration can learn where your confidence has been too high or too low."
        ),
    }


@app.get("/api/market/line-shop")
def line_shop(
    player: str,
    stat: str,
    sport: str = "All Sports",
    platform: str = "Both",
    over_odds: int | None = None,
    under_odds: int | None = None,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _line_shop_payload(player, stat, sport_filter, platform, over_odds, under_odds)


@app.get("/api/market/ev-scanner")
def ev_scanner(
    platform: str = "Both",
    sport: str = "All Sports",
    min_ev: float = 0.0,
    limit: int = 25,
    odds: int = -110,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    rows = _ev_scanner_rows(platform, sport_filter, min_ev, limit, odds)
    return {
        "props": rows,
        "platform": platform,
        "sport": sport,
        "min_ev": min_ev,
        "odds": odds,
        "count": len(rows),
    }


@app.get("/api/market/timing-alerts")
def market_timing_alerts(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    limit: int = 8,
    odds: int = -110,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    rows = _market_timing_alert_rows(platform, sport_filter, limit, odds)
    return {
        "alerts": rows,
        "platform": platform,
        "sport": sport,
        "count": len(rows),
    }


@app.get("/api/market/clv")
def clv_report() -> dict:
    entries = [_entry_clv_payload(entry) for entry in EntryRepository.all()]
    tracked = [entry for entry in entries if entry["legs"]]
    clv_values = [leg["clv"] for entry in tracked for leg in entry["legs"] if leg["clv"] is not None]
    positive = sum(1 for value in clv_values if value > 0)
    return {
        "entries": tracked,
        "average_clv": round(sum(clv_values) / len(clv_values), 2) if clv_values else 0.0,
        "positive_clv_rate": round((positive / len(clv_values) * 100), 1) if clv_values else 0.0,
        "tracked_legs": len(clv_values),
    }


@app.post("/api/sync/run")
def run_sync(allow_estimates: bool = False) -> dict:
    default_wagers = EntryRepository.classify_missing_economics()
    final_stats_file = _import_file_if_configured(
        "EDGEIQ_FINAL_STATS_FILE",
        lambda payload, source: {"imported": import_final_stats(payload, source), "skipped": 0},
    )
    bet_history_file = _import_file_if_configured("EDGEIQ_BET_HISTORY_FILE", _import_betting_history_payload)
    auto_check = auto_check_entries(allow_estimates=allow_estimates)
    return {
        "default_wagers": default_wagers,
        "final_stats_file": final_stats_file,
        "bet_history_file": bet_history_file,
        "auto_check": auto_check,
        "dashboard": get_dashboard(),
        "sportsbook_sync": {
            "connected": False,
            "message": "Direct sportsbook account sync is not configured. EdgeIQ synced provider stats and configured import files.",
        },
    }


class PropPayload(BaseModel):
    player: str
    team: str = ""
    sport: str
    stat: str
    line: float
    projection: float | None = None
    direction: Literal["Over", "Under"] | None = None
    platform: str = "PrizePicks"
    game: str = ""
    trending_count: int = 0


class EntryPayload(BaseModel):
    platform: str = "PrizePicks"
    wager: float = Field(default=0.0, ge=0)
    multiplier: float = Field(default=1.0, ge=1)
    recommended_by_app: bool = False
    props: list[PropPayload]


class AiEntryReviewPayload(EntryPayload):
    question: str = "Should I place this entry?"


@app.post("/api/entries/analyze")
def analyze_entry(payload: EntryPayload) -> dict:
    entry = _entry_from_payload(payload)
    return _entry_analysis(entry)


@app.post("/api/entries/place")
def place_entry(payload: EntryPayload) -> dict:
    if payload.wager <= 0:
        raise HTTPException(status_code=400, detail="Enter an amount wagered before placing the entry.")
    entry = _entry_from_payload(payload)
    entry_id = EntryRepository.save(
        entry,
        status="Pending",
        wager=payload.wager,
        multiplier=payload.multiplier,
        recommended_by_app=payload.recommended_by_app,
    )
    return {
        "id": entry_id,
        "status": "Pending",
        "analysis": _entry_analysis(entry),
        "dashboard": get_dashboard(),
    }


@app.get("/api/entries/pending")
def pending_entries() -> dict:
    return {"entries": [_serialize_pending(entry) for entry in EntryRepository.pending()]}


@app.get("/api/entries/progress")
def entry_progress() -> dict:
    entries = [_entry_progress_payload(entry) for entry in EntryRepository.pending()]
    return {
        "entries": entries,
        "active": len(entries),
        "with_live_stats": sum(1 for entry in entries if entry["source"] == "actual_provider"),
    }


class SettlePayload(BaseModel):
    result: Literal["Win", "Loss", "Push", "DNP"]
    dnp_legs: int = Field(default=0, ge=0)


@app.post("/api/entries/{entry_id}/settle")
def settle_entry(entry_id: int, payload: SettlePayload) -> dict:
    EntryRepository.settle(entry_id, payload.result, payload.dnp_legs, _dnp_mode())
    return {"id": entry_id, "result": payload.result, "status": "Settled", "dashboard": get_dashboard()}


@app.get("/api/entries/suggestions")
def entry_suggestions(
    sport: str = "WNBA",
    platform: str = "PrizePicks",
    leg_count: int = 2,
) -> dict:
    if leg_count < 2 or leg_count > 5:
        raise HTTPException(status_code=400, detail="Leg count must be between 2 and 5.")
    platform_model = _platform_from_text(platform)
    raw_props = _fetch_props(platform_model.value, sport.upper())
    if leg_count == 2:
        suggestions = _mixed_risk_suggestions(raw_props, sport, platform_model)
        mode = "balanced_with_higher_risk"
    else:
        suggestions = suggest_entries(raw_props, sport, platform_model, leg_count=leg_count)
        mode = f"{leg_count}_leg"
    return {
        "suggestions": [_serialize_suggestion(suggestion) for suggestion in suggestions],
        "mode": mode,
    }


@app.get("/api/entries/optimizer")
def optimize_entries(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    min_legs: int = 2,
    max_legs: int = 5,
    limit: int = 5,
    min_confidence: float = 0,
    min_edge: float = -999,
    max_same_team: int = 5,
    exclude_correlated: bool = False,
    apply_feedback: bool = True,
) -> dict:
    if min_legs < 2 or max_legs > 5 or min_legs > max_legs:
        raise HTTPException(status_code=400, detail="Use a leg range between 2 and 5.")
    sport_filter = None if sport == "All Sports" else sport.upper()
    suggestions = _optimized_entries(
        platform,
        sport_filter,
        min_legs,
        max_legs,
        limit,
        min_confidence,
        min_edge,
        max_same_team,
        exclude_correlated,
        apply_feedback,
    )
    return {
        "suggestions": [_serialize_suggestion(suggestion) for suggestion in suggestions],
        "platform": platform,
        "sport": sport,
        "min_legs": min_legs,
        "max_legs": max_legs,
        "filters": {
            "min_confidence": min_confidence,
            "min_edge": min_edge,
            "max_same_team": max_same_team,
            "exclude_correlated": exclude_correlated,
            "apply_feedback": apply_feedback,
        },
    }


@app.get("/api/players/{player_name}")
def player_detail(
    player_name: str,
    platform: str = "Both",
    sport: str = "All Sports",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    props = [
        prop
        for prop in _fetch_props(platform, sport_filter)
        if prop.get("player", "").strip().lower() == player_name.strip().lower()
    ]
    if not props:
        raise HTTPException(status_code=404, detail=f"No active props found for {player_name}.")

    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return _player_detail_payload(player_name, props)


@app.get("/api/players/{player_name}/line-movement")
def player_line_movement(
    player_name: str,
    stat: str,
    platform: str = "PrizePicks",
) -> dict:
    history = LineHistoryRepository.get_history(player_name, stat, platform)
    active_line = _active_line_for_player_stat(player_name, stat, platform)
    return _line_movement_payload(player_name, stat, platform, history, current_line=active_line)


@app.get("/api/players/{player_name}/hit-rate")
def player_hit_rate(
    player_name: str,
    stat: str,
    line: float,
    projection: float | None = None,
    trending_count: int = 0,
    sport: str | None = None,
) -> dict:
    summary = estimate_hit_rate(player_name, stat, line, projection, trending_count, sport)
    return {
        "player": summary.player,
        "stat": summary.stat,
        "line": summary.line,
        "projection": summary.projection,
        "edge": summary.edge,
        "estimated_hit_rate": summary.estimated_hit_rate,
        "last_5": summary.last_5,
        "last_10": summary.last_10,
        "season": summary.season,
        "source": summary.source,
        "sample_size": summary.sample_size,
        "note": summary.note,
    }


@app.post("/api/entries/auto-check")
def auto_check_entries(allow_estimates: bool = False) -> dict:
    pending_entries = EntryRepository.pending()
    refresh = _refresh_final_stats(pending_entries) if pending_entries else {}
    checks = [_check_entry_result(entry, allow_estimates) for entry in pending_entries]
    settled = [check for check in checks if check["settled"]]
    return {
        "checked": len(checks),
        "settled": len(settled),
        "entries": checks,
        "estimated": any(check["source"] == "projection_estimate" for check in checks),
        "final_stats_refresh": refresh,
    }


@app.post("/api/entries/classify-default-wagers")
def classify_default_entry_wagers() -> dict:
    result = EntryRepository.classify_missing_economics()
    return {**result, "dashboard": get_dashboard()}


@app.post("/api/final-stats/import")
def import_final_stats_endpoint(payload: FinalStatsPayload) -> dict:
    imported = import_final_stats(payload.payload, payload.source)
    return {"imported": imported, "source": payload.source}


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


@app.post("/api/bets/import-history")
def import_betting_history(payload: BettingHistoryPayload) -> dict:
    result = _import_betting_history_payload(payload.payload, payload.source)
    return {**result, "dashboard": get_dashboard()}


@app.get("/api/performance")
def performance() -> dict:
    stats = get_dashboard()
    return {
        "bankroll_curve": stats.get("bankroll_curve", []),
        "by_sport": stats.get("by_sport", {}),
        "by_stat": stats.get("by_stat", {}),
        "by_platform": stats.get("by_platform", {}),
        "entries": stats.get("entries", {}),
        "summary": stats,
    }


@app.get("/api/analytics/backtest")
def backtest() -> dict:
    return backtest_summary(BetRepository().get_all(), EntryRepository.all())


@app.get("/api/analytics/model-health")
def model_health() -> dict:
    return _model_health_payload()


def _import_betting_history_payload(payload: str, source: str) -> dict:
    imported = 0
    skipped = 0
    for row in _parse_betting_history(payload):
        try:
            result = row.get("result", "").strip().title()
            if result not in {"Win", "Loss", "Push"}:
                skipped += 1
                continue
            wager = float(row.get("wager") or row.get("amount") or 0)
            if wager <= 0:
                skipped += 1
                continue
            odds = int(float(row.get("odds") or -110))
            profit_value = row.get("profit")
            if profit_value in (None, ""):
                if result == "Win":
                    profit = potential_profit(odds, wager)
                elif result == "Loss":
                    profit = -wager
                else:
                    profit = 0.0
            else:
                profit = float(profit_value)
            BetRepository().save(
                Bet(
                    sport=row.get("sport", ""),
                    game=row.get("game", ""),
                    description=row.get("description") or row.get("bet") or row.get("pick") or "Imported bet",
                    odds=odds,
                    wager=wager,
                    result=result,
                    profit=round(profit, 2),
                    platform=row.get("platform", source),
                    stat_type=row.get("stat_type") or row.get("stat", ""),
                    win_probability=float(row.get("win_probability") or row.get("probability") or 0),
                )
            )
            imported += 1
        except (TypeError, ValueError):
            skipped += 1
    return {"imported": imported, "skipped": skipped}


def _fetch_props(platform: str, sport_filter: str | None) -> list[dict]:
    selected = _selected_platforms(platform)
    props: list[dict] = []
    for platform_name in selected:
        props.extend(_fetch_platform_props(platform_name))

    if sport_filter:
        props = [prop for prop in props if prop.get("league", "").upper() == sport_filter]
    _record_line_snapshots(props)
    return props


def _fetch_platform_props(platform: str) -> list[dict]:
    providers = {
        "PrizePicks": lambda: prizepicks.fetch_projections(limit=1000),
        "Underdog": underdog.fetch_projections,
        "Sleeper": sleeper.fetch_projections,
        "Chalkboard": chalkboard.fetch_projections,
        "Betr": betr.fetch_projections,
        "Ball Don't Lie": lambda: balldontlie.fetch_props(),
    }
    fetcher = providers.get(_canonical_platform(platform))
    if fetcher is None:
        return []
    try:
        props = fetcher()
    except Exception:
        return []
    for prop in props:
        prop.setdefault("platform", _canonical_platform(platform))
    return props


def _selected_platforms(platform: str) -> list[str]:
    canonical = _canonical_platform(platform)
    if canonical == "Both":
        return list(PROP_PLATFORMS)
    return [canonical] if canonical in PROP_PLATFORMS else ["PrizePicks"]


def _canonical_platform(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"both", "all", "all platforms"}:
        return "Both"
    for platform in PROP_PLATFORMS:
        if platform.lower() == normalized:
            return platform
    return "PrizePicks"


def _refresh_final_stats(pending_entries: list[dict]) -> dict:
    espn_refresh = refresh_final_stats_for_entries(pending_entries)
    sportsdataio_refresh = _sportsdataio_refresh(pending_entries)
    return {
        "providers": ["espn", "sportsdataio"],
        "provider": "espn+sportsdataio",
        "espn": espn_refresh,
        "sportsdataio": sportsdataio_refresh,
        "imported": espn_refresh.get("imported", 0) + sportsdataio_refresh.get("imported", 0),
        "fetched_rows": espn_refresh.get("fetched_rows", 0) + sportsdataio_refresh.get("fetched_rows", 0),
        "errors": espn_refresh.get("errors", []) + sportsdataio_refresh.get("errors", []),
    }


def _sportsdataio_refresh(pending_entries: list[dict]) -> dict:
    from datetime import timedelta

    rows = []
    errors = []
    sports = sorted({
        str(prop.get("sport", "")).upper()
        for entry in pending_entries
        for prop in entry.get("props", [])
        if str(prop.get("sport", "")).upper() in {"NBA", "NFL", "MLB"}
    })
    dates = sorted({
        entry["placed_at"].date()
        for entry in pending_entries
        if hasattr(entry.get("placed_at"), "date")
    })
    if not dates:
        dates = [datetime.utcnow().date()]
    window = sorted({day + timedelta(days=offset) for day in dates for offset in range(-2, 3)})
    for sport in sports:
        for day in window:
            try:
                rows.extend(sportsdataio.fetch_final_stats(sport, day))
            except RuntimeError as exc:
                errors.append(f"{sport} {day.isoformat()}: {exc}")
    imported = 0
    if rows:
        from repository.repositories.final_stats_repository import FinalStatsRepository

        imported = FinalStatsRepository.upsert_many(rows)
    return {
        "provider": "sportsdataio",
        "sports": sports,
        "dates": [day.isoformat() for day in window],
        "fetched_rows": len(rows),
        "imported": imported,
        "errors": errors,
    }


def _parse_betting_history(payload: str) -> list[dict]:
    stripped = payload.strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            parsed = parsed.get("bets", [])
        return [dict(row) for row in parsed if isinstance(row, dict)]

    reader = csv.DictReader(StringIO(stripped))
    rows = []
    for row in reader:
        normalized = {
            (key or "").strip().lower().replace(" ", "_"): (value or "").strip()
            for key, value in row.items()
        }
        rows.append(normalized)
    return rows


def _import_file_if_configured(env_name: str, importer) -> dict:
    file_path = os.getenv(env_name, "").strip()
    if not file_path:
        return {"configured": False, "imported": 0, "skipped": 0, "message": f"{env_name} is not set."}
    path = Path(file_path).expanduser()
    if not path.exists():
        return {"configured": True, "imported": 0, "skipped": 0, "message": f"{path} was not found."}
    try:
        payload = path.read_text(encoding="utf-8")
        result = importer(payload, path.stem)
        return {"configured": True, "message": f"Imported {path.name}.", **result}
    except Exception as exc:
        return {
            "configured": True,
            "imported": 0,
            "skipped": 0,
            "message": f"Could not import {path.name}: {exc.__class__.__name__}",
        }


def _parse_parlay_request(message: str, selected_sport: str = "All Sports") -> dict:
    text = f" {message or ''} ".upper().replace("-", " ")
    leg_count = 3
    for count in range(2, 7):
        tokens = (
            f" {count} LEG ",
            f" {count} LEGS ",
            f" {count} PICK ",
            f" {count} PICKS ",
            f" {count} MAN ",
        )
        if any(token in text for token in tokens):
            leg_count = count
            break
    leg_count = max(2, min(5, leg_count))

    sport = _sport_filter_from_text(message)
    if sport is None and selected_sport != "All Sports":
        sport = _sport_filter_from_text(selected_sport)

    return {
        "leg_count": leg_count,
        "sport": sport,
        "sport_label": sport or "All Sports",
    }


def _sport_filter_from_text(value: str) -> str | None:
    normalized = (value or "").upper()
    normalized = normalized.replace("-", " ").replace("_", " ")
    for phrase, sport in sorted(SPORT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if phrase in normalized:
            return sport
    direct = normalized.strip()
    if direct in SUPPORTED_SPORTS:
        return direct
    return None


def _fallback_parlay_chat(suggestions: list[dict], request: dict | None = None) -> str:
    request = request or {"leg_count": 3, "sport_label": "current filters"}
    leg_count = int(request.get("leg_count") or 3)
    sport_label = request.get("sport_label") or "current filters"
    if not suggestions:
        return f"I could not find a {leg_count}-leg parlay for {sport_label}. Try another sport or platform."
    best = suggestions[0]
    legs = best["entry"]["props"]
    leg_text = " + ".join(
        f"{prop['player']} {prop.get('direction', 'Over')} {prop['stat']} {prop['line']}"
        for prop in legs
    )
    caution = (
        "I would not place it unless you are comfortable with the risk."
        if best["grade"] in {"D", "F"} or "Pass" in best["action"]
        else "It is the strongest candidate on the board, but still review the legs before placing anything."
    )
    return (
        f"My best {leg_count}-leg parlay for {sport_label} right now is {leg_text}. "
        f"It grades {best['grade']} with a score of {best['score']} and the model action is {best['action']}. "
        f"{caution}"
    )


def _fallback_entry_review(analysis: dict) -> str:
    rec = analysis.get("recommendation", {})
    risk = analysis.get("risk", {})
    warnings = analysis.get("warnings", [])
    warning_text = f" Main flags: {'; '.join(warnings[:3])}." if warnings else ""
    return (
        f"Rules review: {rec.get('action', 'Review')} with grade {rec.get('grade', '-')}. "
        f"Average confidence is {risk.get('average_confidence', 0)}% and risk is {risk.get('level', 'Unknown')}. "
        f"{rec.get('reason', '')}{warning_text}"
    ).strip()


def _decode_uploaded_bytes(content_base64: str) -> bytes:
    try:
        return base64.b64decode(content_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Upload content is not valid base64.") from exc


def _is_image_upload(payload: UploadAnalyzePayload) -> bool:
    name = payload.file_name.lower()
    return payload.mime_type.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp"))


def _analyze_uploaded_text_file(payload: UploadAnalyzePayload, raw: bytes) -> dict:
    text = _decode_text(raw)
    if payload.target == "final_stats":
        imported = import_final_stats(text, payload.source or "upload")
        return {
            "kind": "final_stats",
            "file_name": payload.file_name,
            "imported": imported,
            "message": f"Imported {imported} final stat rows.",
        }
    if payload.target == "bet_history":
        rows = _parse_betting_history(text)
        imported = _import_betting_rows(rows, payload.source or "upload")
        return {
            "kind": "bet_history",
            "file_name": payload.file_name,
            **imported,
            "message": f"Imported {imported['imported']} bets. Skipped {imported['skipped']}.",
        }

    props = _props_from_uploaded_text(text, payload.source or "Upload")
    analysis = _analysis_from_uploaded_props(props)
    return {
        "kind": "props",
        "file_name": payload.file_name,
        "props": props,
        "prop_count": len(props),
        "analysis": analysis,
        "message": f"Extracted {len(props)} props from {payload.file_name}.",
    }


def _analyze_uploaded_image(payload: UploadAnalyzePayload, raw: bytes) -> dict:
    if payload.target == "bet_history":
        extracted = _openai_extract_bets_from_image(raw, payload.mime_type or "image/png")
        if extracted is None:
            return {
                "kind": "bet_history",
                "file_name": payload.file_name,
                "imported": 0,
                "skipped": 0,
                "ai_enabled": False,
                "message": "Bet-history screenshot parsing needs OPENAI_API_KEY. CSV, TSV, TXT, and JSON history files can still be imported locally.",
            }
        rows = extracted.get("bets", [])
        imported = _import_betting_rows(rows, extracted.get("platform") or payload.source or "screenshot")
        return {
            "kind": "bet_history",
            "file_name": payload.file_name,
            **imported,
            "ai_enabled": True,
            "raw_ai": extracted,
            "message": f"Imported {imported['imported']} bets from screenshot. Skipped {imported['skipped']}.",
        }

    extracted = _openai_extract_props_from_image(raw, payload.mime_type or "image/png")
    if extracted is None:
        return {
            "kind": "image",
            "file_name": payload.file_name,
            "props": [],
            "prop_count": 0,
            "analysis": None,
            "ai_enabled": False,
            "message": "Screenshot parsing needs OPENAI_API_KEY. Text, CSV, TSV, and JSON files can be analyzed locally.",
        }

    props = _normalize_uploaded_props(extracted.get("props", []), extracted.get("platform") or payload.source or "Upload")
    analysis = _analysis_from_uploaded_props(props)
    return {
        "kind": "image",
        "file_name": payload.file_name,
        "props": props,
        "prop_count": len(props),
        "analysis": analysis,
        "ai_enabled": True,
        "raw_ai": extracted,
        "message": f"Extracted {len(props)} props from screenshot.",
    }


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail="Could not decode this file as text.")


def _props_from_uploaded_text(text: str, platform: str) -> list[dict]:
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            platform = parsed.get("platform") or platform
            rows = parsed.get("props") or parsed.get("projections") or parsed.get("lines") or []
        else:
            rows = parsed
        return _normalize_uploaded_props(rows, platform)
    return [_uploaded_prop_payload(prop) for prop in normalize_props(_normalize_delimited_text(stripped), platform)]


def _normalize_delimited_text(text: str) -> str:
    if "\t" in text.splitlines()[0]:
        rows = csv.reader(StringIO(text), delimiter="\t")
        output = StringIO()
        writer = csv.writer(output)
        writer.writerows(rows)
        return output.getvalue()
    return text


def _normalize_uploaded_props(rows: list[dict], platform: str) -> list[dict]:
    props = normalize_props(rows, platform)
    return [_uploaded_prop_payload(prop) for prop in props]


def _uploaded_prop_payload(prop: dict) -> dict:
    return {
        "player": prop.get("player", ""),
        "team": prop.get("team", ""),
        "sport": prop.get("league", prop.get("sport", "WNBA")) or "WNBA",
        "stat": prop.get("stat", "Points"),
        "line": float(prop.get("line") or 0.0),
        "projection": prop.get("projection"),
        "direction": prop.get("direction") or prop.get("pick") or prop.get("side"),
        "platform": prop.get("platform", "Upload"),
        "game": prop.get("game", ""),
        "trending_count": int(prop.get("trending_count") or 0),
    }


def _analysis_from_uploaded_props(props: list[dict]) -> dict | None:
    if len(props) < 2:
        return None
    try:
        payload = EntryPayload.model_validate({
            "platform": props[0].get("platform") or "PrizePicks",
            "props": props,
        })
    except Exception:
        return None
    return analyze_entry(payload)


def _import_betting_rows(rows: list[dict], source: str) -> dict:
    imported = 0
    skipped = 0
    for row in rows:
        try:
            odds = int(float(row.get("odds") or -110))
            wager = float(row.get("wager") or 0)
            result = row.get("result", "").strip().title()
            if result not in {"Win", "Loss", "Push"} or wager <= 0:
                skipped += 1
                continue
            profit = row.get("profit")
            if profit in (None, ""):
                if result == "Win":
                    profit = potential_profit(odds, wager)
                elif result == "Loss":
                    profit = -wager
                else:
                    profit = 0.0
            BetRepository().save(Bet(
                sport=row.get("sport", ""),
                game=row.get("game", ""),
                description=row.get("description", row.get("bet", "")),
                odds=odds,
                wager=wager,
                result=result,
                profit=round(float(profit), 2),
                platform=row.get("platform", source),
                stat_type=row.get("stat_type", row.get("stat", "")),
                win_probability=float(row.get("win_probability") or 0),
            ))
            imported += 1
        except (TypeError, ValueError):
            skipped += 1
    return {"imported": imported, "skipped": skipped}


def _openai_extract_props_from_image(raw: bytes, mime_type: str) -> dict | None:
    return _openai_extract_json_from_image(
        raw,
        mime_type,
        (
            "Extract player prop picks from this screenshot. Return only JSON with this shape: "
            "{\"platform\":\"PrizePicks|Underdog|Sleeper|Chalkboard|Betr|Unknown\","
            "\"props\":[{\"player\":\"\",\"team\":\"\",\"sport\":\"WNBA|NBA|NFL|MLB\","
            "\"stat\":\"\",\"line\":0,\"projection\":null,\"game\":\"\"}],"
            "\"notes\":[]}. Use null when a projection is not shown. Do not invent missing props."
        ),
        max_output_tokens=700,
    )


def _openai_extract_bets_from_image(raw: bytes, mime_type: str) -> dict | None:
    return _openai_extract_json_from_image(
        raw,
        mime_type,
        (
            "Extract previous bet history from this phone screenshot. Return only JSON with this shape: "
            "{\"platform\":\"PrizePicks|Underdog|Sleeper|Chalkboard|Betr|Unknown\","
            "\"bets\":[{\"sport\":\"\",\"game\":\"\",\"description\":\"\",\"odds\":-110,"
            "\"wager\":0,\"result\":\"Win|Loss|Push\",\"profit\":null,\"stat_type\":\"\","
            "\"win_probability\":null}],\"notes\":[]}. "
            "Use the amount risked as wager. If profit is not shown, use null. "
            "If odds are not shown, use -110. Do not invent bets that are not visible."
        ),
        max_output_tokens=900,
    )


def _openai_extract_json_from_image(
    raw: bytes,
    mime_type: str,
    instruction: str,
    max_output_tokens: int = 700,
) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    image_data = base64.b64encode(raw).decode("utf-8")
    payload = {
        "model": _openai_vision_model(),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": instruction,
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{image_data}",
                    },
                ],
            }
        ],
        "max_output_tokens": max_output_tokens,
    }

    response_data, _ = _openai_response(payload, timeout=30)
    if response_data is None:
        return None

    text = _response_output_text(response_data)
    if not text:
        return None
    return _parse_json_from_model_text(text)


def _response_output_text(data: dict) -> str | None:
    text = data.get("output_text")
    if text:
        return text.strip()

    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip() or None


def _parse_json_from_model_text(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _openai_parlay_response(message: str, suggestions: list[dict]) -> tuple[str | None, str | None]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or not suggestions:
        return None, "missing_key" if not api_key else "no_candidates"

    payload = {
        "model": _openai_model(),
        "input": [
            {
                "role": "system",
                "content": (
                    "You are EdgeIQ's betting assistant. Pick only from the provided parlay candidates. "
                    "Do not invent players, lines, odds, or guaranteed outcomes. Keep the response concise, "
                    "include each leg's Over or Under direction, explain why it ranks first, and remind the user to bet responsibly."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"user_message": message, "candidates": suggestions[:5]},
                    default=str,
                ),
            },
        ],
        "max_output_tokens": 350,
    }

    data, error = _openai_response(payload, timeout=20)
    if data is None:
        return None, error

    return _response_output_text(data), None


def _openai_entry_review(question: str, analysis: dict) -> tuple[str | None, str | None]:
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return None, "missing_key"
    payload = {
        "model": _openai_model(),
        "input": [
            {
                "role": "system",
                "content": (
                    "You are EdgeIQ's AI entry reviewer. You review only the supplied app analysis. "
                    "Do not invent new stats, injuries, lines, or results. Be concise, practical, and risk-aware. "
                    "Never promise a win. Highlight the strongest leg, weakest leg, source-signal conflicts, and final action."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"question": question, "analysis": analysis}, default=str),
            },
        ],
        "max_output_tokens": 500,
    }
    data, error = _openai_response(payload, timeout=25)
    if data is None:
        return None, error
    return _response_output_text(data), None


def _openai_response(payload: dict, timeout: int = 20) -> tuple[dict | None, str | None]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, "missing_key"
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        detail = _openai_error_detail(exc.response)
        return None, f"openai_http_{status}: {detail}"
    except requests.RequestException as exc:
        return None, f"openai_request_error: {exc.__class__.__name__}"


def _openai_error_detail(response) -> str:
    if response is None:
        return "No response body."
    try:
        data = response.json()
        message = data.get("error", {}).get("message")
        return str(message or response.text[:160])
    except ValueError:
        return response.text[:160]


def _openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5").strip() or "gpt-5"


def _openai_vision_model() -> str:
    return os.getenv("OPENAI_VISION_MODEL", _openai_model()).strip() or _openai_model()



def _record_line_snapshots(props: list[dict]) -> None:
    seen: set[tuple[str, str, str]] = set()
    ranked_props = sorted(props, key=lambda prop: prop.get("trending_count", 0), reverse=True)
    for prop in ranked_props:
        line = prop.get("line")
        if line is None:
            continue
        player = prop.get("player", "")
        stat = prop.get("stat", "")
        platform = prop.get("platform", "PrizePicks")
        if not player or not stat:
            continue
        key = (player.strip().lower(), stat.strip().lower(), platform.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        LineHistoryRepository.record(player, stat, platform, float(line))


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


def _top_props_by_sport(props: list[dict], limit: int, sport_filter: str | None = None) -> list[dict]:
    if sport_filter:
        return _with_sport_rank(_unique_player_props(props, limit), sport_filter)

    grouped: dict[str, list[dict]] = {}
    for prop in props:
        sport = prop.get("league", "Other").upper()
        sport_props = grouped.setdefault(sport, [])
        if len(sport_props) >= limit:
            continue
        player_key = prop.get("player", "").strip().lower()
        if not player_key:
            continue
        if any(existing.get("player", "").strip().lower() == player_key for existing in sport_props):
            continue
        ranked_prop = dict(prop)
        ranked_prop["direction"] = _feed_prop_direction(ranked_prop)
        ranked_prop["sport_rank"] = len(sport_props) + 1
        sport_props.append(ranked_prop)

    ordered_sports = sorted(grouped)
    return [prop for sport in ordered_sports for prop in grouped[sport]]


def _with_sport_rank(props: list[dict], sport: str) -> list[dict]:
    ranked = []
    for index, prop in enumerate(props, start=1):
        ranked_prop = dict(prop)
        ranked_prop["direction"] = _feed_prop_direction(ranked_prop)
        ranked_prop["sport_rank"] = index
        ranked_prop["league"] = ranked_prop.get("league") or sport
        ranked.append(ranked_prop)
    return ranked


def _feed_prop_direction(prop: dict) -> str:
    line = float(prop.get("line") or 0.0)
    projection = prop.get("projection")
    if projection is None:
        projection = auto_projection(line, int(prop.get("trending_count") or 0))
    return _prop_direction(line, float(projection), prop.get("direction"))


def _trending_games_payload(props: list[dict], ranked_props: list[dict], limit: int) -> list[dict]:
    ranked_players = {
        (prop.get("player", "").strip().lower(), prop.get("league", "").strip().upper())
        for prop in ranked_props
    }
    grouped: dict[tuple[str, str], dict] = {}

    for prop in props:
        game = str(prop.get("game", "")).strip()
        sport = str(prop.get("league", "")).strip().upper()
        if not game or not sport:
            continue
        key = (sport, game)
        group = grouped.setdefault(
            key,
            {
                "sport": sport,
                "game": game,
                "trending_count": 0,
                "prop_count": 0,
                "players": {},
                "ranked_players": {},
            },
        )
        player = str(prop.get("player", "")).strip()
        if not player:
            continue
        trend = int(prop.get("trending_count") or 0)
        group["trending_count"] += trend
        group["prop_count"] += 1
        player_row = group["players"].setdefault(
            player,
            {"player": player, "team": prop.get("team", ""), "trending_count": 0, "ranked": False},
        )
        player_row["trending_count"] += trend
        if (player.strip().lower(), sport) in ranked_players:
            player_row["ranked"] = True
            group["ranked_players"][player] = player_row

    games = []
    for group in grouped.values():
        players = sorted(group["players"].values(), key=lambda row: row["trending_count"], reverse=True)
        ranked = sorted(group["ranked_players"].values(), key=lambda row: row["trending_count"], reverse=True)
        games.append({
            "sport": group["sport"],
            "game": group["game"],
            "trending_count": group["trending_count"],
            "prop_count": group["prop_count"],
            "ranked_player_count": len(ranked),
            "ranked_players": ranked[:6],
            "top_players": players[:6],
        })

    games.sort(key=lambda game: (game["ranked_player_count"], game["trending_count"]), reverse=True)
    return games[:limit]


def _recommended_parlay(platform: str, sport_filter: str | None):
    best = None
    for platform_model, props in _props_by_platform(platform):
        sports = [sport_filter] if sport_filter else sorted({prop.get("league", "").upper() for prop in props if prop.get("league")})
        for sport in sports:
            suggestions = suggest_entries(props, sport, platform_model, limit=1, leg_count=3)
            if suggestions and (best is None or suggestions[0].score > best.score):
                best = suggestions[0]
    return best


def _command_center_payload(platform: str, sport_filter: str | None) -> dict:
    dashboard_stats = get_dashboard()
    props = _fetch_props(platform, sport_filter)
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    ranked_props = [_analyzed_feed_prop(prop) for prop in _top_props_by_sport(props, 5, sport_filter)]
    ranked_props.sort(key=lambda prop: (prop["confidence"], prop["edge"], prop["trending_count"]), reverse=True)

    safe_slips = _optimized_entries(
        platform,
        sport_filter,
        min_legs=2,
        max_legs=2,
        limit=1,
        min_confidence=52,
        min_edge=0,
        max_same_team=1,
        exclude_correlated=True,
        apply_feedback=True,
    )
    balanced_slips = _optimized_entries(
        platform,
        sport_filter,
        min_legs=3,
        max_legs=3,
        limit=1,
        min_confidence=0,
        min_edge=-999,
        max_same_team=1,
        exclude_correlated=True,
        apply_feedback=True,
    )
    high_risk_slips = _optimized_entries(
        platform,
        sport_filter,
        min_legs=4,
        max_legs=5,
        limit=2,
        min_confidence=0,
        min_edge=-999,
        max_same_team=1,
        exclude_correlated=True,
        apply_feedback=True,
    )

    cards = []
    if ranked_props:
        cards.append(_command_single_card(ranked_props[0]))
    if safe_slips:
        cards.append(_command_suggestion_card("Safer Slip", "Lower volatility entry to start with.", safe_slips[0]))
    if balanced_slips:
        cards.append(_command_suggestion_card("Best 3-Leg", "Primary daily parlay candidate.", balanced_slips[0]))
    for suggestion in high_risk_slips[:2]:
        cards.append(_command_suggestion_card(f"Upside {suggestion.entry.prop_count}-Leg", "Higher variance, sized smaller.", suggestion))

    avoid = [
        prop for prop in ranked_props
        if prop["confidence"] < 50 or prop["edge"] < 0
    ][:3]
    model = _model_health_payload()
    return {
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "as_of": datetime.now().isoformat(),
        "cards": cards[:5],
        "avoid": avoid,
        "model_health": model,
        "bankroll": {
            "current": dashboard_stats.get("bankroll", 0.0),
            "pending_exposure": dashboard_stats.get("pending_entry_exposure", 0.0),
            "recommendation_accuracy": dashboard_stats.get("recommendation_accuracy", {}),
        },
    }


def _command_single_card(prop: dict) -> dict:
    return {
        "type": "single",
        "title": "Best Single",
        "summary": "Highest-confidence prop on the current board.",
        "score": round((prop["confidence"] * 0.78) + (prop["edge"] * 7) + min(8, prop["trending_count"] / 20000), 1),
        "grade": _grade_from_confidence(prop["confidence"]),
        "action": f"{prop['direction']} {prop['stat']}",
        "props": [prop],
        "warnings": [],
        "explanation": _recommendation_explanation(
            title="Best Single",
            score=round(prop["confidence"], 1),
            grade=_grade_from_confidence(prop["confidence"]),
            props=[prop],
            warnings=[],
            summary="Chosen from the top board by confidence, projected edge, and market interest.",
        ),
    }


def _command_suggestion_card(title: str, summary: str, suggestion) -> dict:
    serialized = _serialize_suggestion(suggestion)
    return {
        "type": "entry",
        "title": title,
        "summary": summary,
        "score": serialized["score"],
        "grade": serialized["grade"],
        "action": serialized["action"],
        "leg_count": serialized["leg_count"],
        "risk_tier": serialized["risk_tier"],
        "suggestion": serialized,
        "props": serialized["entry"]["props"],
        "warnings": serialized["warnings"],
        "explanation": _recommendation_explanation(
            title=title,
            score=serialized["score"],
            grade=serialized["grade"],
            props=serialized["entry"]["props"],
            warnings=serialized["warnings"],
            summary=summary,
        ),
    }


def _recommendation_explanation(
    title: str,
    score: float,
    grade: str,
    props: list[dict],
    warnings: list[str],
    summary: str,
) -> dict:
    avg_confidence = sum(float(prop.get("confidence") or 0) for prop in props) / len(props) if props else 0.0
    avg_edge = sum(float(prop.get("edge") or 0) for prop in props) / len(props) if props else 0.0
    sources = sorted({
        signal.get("source", "")
        for prop in props
        for signal in prop.get("source_signals", [])
        if signal.get("source")
    })
    signals = [
        {
            "source": signal.get("source", ""),
            "message": signal.get("message", ""),
            "player": prop.get("player", ""),
        }
        for prop in props
        for signal in prop.get("source_signals", [])[:2]
    ][:5]
    return {
        "title": title,
        "summary": summary,
        "grade": grade,
        "score": score,
        "average_confidence": round(avg_confidence, 1),
        "average_edge": round(avg_edge, 2),
        "source_count": len(sources),
        "sources": sources,
        "signals": signals,
        "warnings": warnings,
        "legs": [
            {
                "player": prop.get("player", ""),
                "pick": f"{prop.get('direction', 'Over')} {prop.get('stat', '')} {prop.get('line', '')}",
                "projection": prop.get("projection"),
                "confidence": prop.get("confidence"),
                "edge": prop.get("edge"),
                "platform": prop.get("platform", ""),
                "sport": prop.get("sport", ""),
            }
            for prop in props
        ],
    }


def _grade_from_confidence(confidence: float) -> str:
    if confidence >= 70:
        return "A"
    if confidence >= 62:
        return "B"
    if confidence >= 54:
        return "C"
    if confidence >= 48:
        return "D"
    return "F"


def _model_health_payload() -> dict:
    backtest_data = backtest_summary(BetRepository().get_all(), EntryRepository.all())
    entry_confidence = backtest_data.get("entries", {}).get("confidence", {})
    calibration = backtest_data.get("calibration", [])
    calibrated_rows = sum(bucket.get("bets", 0) for bucket in calibration)
    avg_error = (
        sum(abs(bucket.get("error", 0.0)) * bucket.get("bets", 0) for bucket in calibration) / calibrated_rows
        if calibrated_rows
        else 0.0
    )
    settled_entries = backtest_data.get("entries", {}).get("count", 0)
    ai = ai_status()
    dashboard_stats = get_dashboard()
    source_score = min(100.0, 35.0 + (calibrated_rows * 2.5) + (settled_entries * 3.0))
    calibration_score = max(0.0, 100.0 - (avg_error * 2.0)) if calibrated_rows else 45.0
    confidence_edge = abs(float(entry_confidence.get("edge") or 0.0))
    confidence_score = max(0.0, 100.0 - (confidence_edge * 2.0)) if settled_entries else 50.0
    ai_score = 100.0 if ai["configured"] and ai["key_format_ok"] else 55.0
    recommendation_accuracy = dashboard_stats.get("recommendation_accuracy", {})
    rec_accuracy = float(recommendation_accuracy.get("accuracy") or 0.0)
    accuracy_score = rec_accuracy if recommendation_accuracy.get("tracked") else 50.0
    trust_score = round(
        (calibration_score * 0.34)
        + (confidence_score * 0.22)
        + (source_score * 0.18)
        + (ai_score * 0.12)
        + (accuracy_score * 0.14),
        1,
    )
    if trust_score >= 78:
        status = "Strong"
    elif trust_score >= 62:
        status = "Usable"
    elif trust_score >= 48:
        status = "Learning"
    else:
        status = "Needs Data"

    return {
        "trust_score": trust_score,
        "status": status,
        "settled_entries": settled_entries,
        "calibrated_picks": calibrated_rows,
        "average_calibration_error": round(avg_error, 1),
        "actual_vs_confidence_edge": entry_confidence.get("edge", 0.0),
        "openai": ai,
        "recommendation_accuracy": recommendation_accuracy,
        "components": {
            "calibration": round(calibration_score, 1),
            "confidence_alignment": round(confidence_score, 1),
            "data_depth": round(source_score, 1),
            "ai_readiness": round(ai_score, 1),
            "recommendation_accuracy": round(accuracy_score, 1),
        },
        "next_steps": _model_health_next_steps(calibrated_rows, settled_entries, ai, avg_error),
    }


def _model_health_next_steps(calibrated_rows: int, settled_entries: int, ai: dict, avg_error: float) -> list[str]:
    steps = []
    if calibrated_rows < 25:
        steps.append("Upload or import more betting history to strengthen confidence calibration.")
    if settled_entries < 10:
        steps.append("Settle more EdgeIQ-recommended entries so the model can learn from its own calls.")
    if not (ai.get("configured") and ai.get("key_format_ok")):
        steps.append("Connect a valid OpenAI API key for richer reasoning and screenshot extraction.")
    if avg_error > 15:
        steps.append("Review high-confidence misses in Performance before increasing bet size.")
    return steps or ["Model inputs look healthy. Keep logging results to preserve calibration."]


def _optimized_entries(
    platform: str,
    sport_filter: str | None,
    min_legs: int,
    max_legs: int,
    limit: int,
    min_confidence: float = 0.0,
    min_edge: float = -999.0,
    max_same_team: int = 5,
    exclude_correlated: bool = False,
    apply_feedback: bool = True,
) -> list:
    ranked = []
    for platform_model, props in _props_by_platform(platform):
        sports = [sport_filter] if sport_filter else sorted({prop.get("league", "").upper() for prop in props if prop.get("league")})
        for sport in sports:
            for leg_count in range(min_legs, max_legs + 1):
                ranked.extend(
                    suggest_entries(
                        props,
                        sport,
                        platform_model,
                        limit=limit,
                        leg_count=leg_count,
                        min_confidence=min_confidence,
                        min_edge=min_edge,
                        max_same_team=max_same_team,
                        exclude_correlated=exclude_correlated,
                        apply_feedback=apply_feedback,
                    )
                )

    ranked.sort(key=lambda suggestion: suggestion.score, reverse=True)
    for rank, suggestion in enumerate(ranked[:limit], start=1):
        suggestion.rank = rank
    return ranked[:limit]


def _mixed_risk_suggestions(raw_props: list[dict], sport: str, platform_model: Platform) -> list:
    suggestions = suggest_entries(raw_props, sport, platform_model, limit=3, leg_count=2)
    for high_risk_leg_count in (4, 5):
        high_risk = suggest_entries(
            raw_props,
            sport,
            platform_model,
            limit=1,
            leg_count=high_risk_leg_count,
            max_same_team=1,
            exclude_correlated=True,
            apply_feedback=True,
        )
        if not high_risk:
            high_risk = suggest_entries(
                raw_props,
                sport,
                platform_model,
                limit=1,
                leg_count=high_risk_leg_count,
            )
        suggestions.extend(high_risk[:1])

    for rank, suggestion in enumerate(suggestions[:5], start=1):
        suggestion.rank = rank
    return suggestions[:5]


def _props_by_platform(platform: str) -> list[tuple[Platform, list[dict]]]:
    platforms: list[tuple[Platform, list[dict]]] = []
    for platform_name in _selected_platforms(platform):
        platform_model = _platform_from_text(platform_name)
        props = _fetch_platform_props(platform_name)
        if props:
            platforms.append((platform_model, props))
    return platforms


def _player_detail_payload(player_name: str, props: list[dict]) -> dict:
    analyzed_props = [_analyzed_feed_prop(prop) for prop in props]
    best_prop = max(analyzed_props, key=lambda prop: (prop["confidence"], prop["trending_count"]))
    sports = sorted({prop["sport"] for prop in analyzed_props if prop["sport"]})
    teams = sorted({prop["team"] for prop in analyzed_props if prop["team"]})
    games = sorted({prop["game"] for prop in analyzed_props if prop["game"]})
    return {
        "player": player_name,
        "teams": teams,
        "sports": sports,
        "games": games,
        "prop_count": len(analyzed_props),
        "average_confidence": round(sum(prop["confidence"] for prop in analyzed_props) / len(analyzed_props), 2),
        "average_edge": round(sum(prop["edge"] for prop in analyzed_props) / len(analyzed_props), 2),
        "best_prop": best_prop,
        "props": analyzed_props,
    }


def _analyzed_feed_prop(raw: dict) -> dict:
    line = float(raw.get("line") or 0)
    trending_count = int(raw.get("trending_count") or 0)
    projection = auto_projection(line, trending_count)
    edge = calculate_edge(line, projection)
    direction = _prop_direction(line, projection, raw.get("direction"))
    platform = raw.get("platform", "PrizePicks")
    movement = _line_movement_payload(
        raw.get("player", ""),
        raw.get("stat", ""),
        platform,
        LineHistoryRepository.get_history(raw.get("player", ""), raw.get("stat", ""), platform),
        current_line=line,
    )
    hit_rate = estimate_hit_rate(
        raw.get("player", ""),
        raw.get("stat", ""),
        line,
        projection,
        trending_count,
        raw.get("league", ""),
    )
    return {
        "player": raw.get("player", ""),
        "team": raw.get("team", ""),
        "sport": raw.get("league", ""),
        "stat": raw.get("stat", ""),
        "line": line,
        "projection": projection,
        "direction": direction,
        "edge": round(edge, 2),
        "confidence": round(calculate_confidence(edge), 2),
        "platform": platform,
        "game": raw.get("game", ""),
        "trending_count": trending_count,
        "line_movement": movement,
        "hit_rate": {
            "estimated_hit_rate": hit_rate.estimated_hit_rate,
            "last_5": hit_rate.last_5,
            "last_10": hit_rate.last_10,
            "season": hit_rate.season,
            "source": hit_rate.source,
            "note": hit_rate.note,
        },
    }


def _line_shop_payload(
    player: str,
    stat: str,
    sport_filter: str | None,
    platform: str,
    over_odds: int | None = None,
    under_odds: int | None = None,
) -> dict:
    props = _matching_market_props(player, stat, sport_filter, platform)
    if not props:
        return {
            "player": player,
            "stat": stat,
            "sport": sport_filter or "All Sports",
            "available": False,
            "message": "No active matching prop lines found.",
            "lines": [],
            "best_over": None,
            "best_under": None,
            "consensus_line": None,
            "no_vig": _no_vig_payload(over_odds, under_odds),
        }

    analyzed = [_analyzed_feed_prop(prop) for prop in props]
    analyzed.sort(key=lambda prop: (prop["line"], -prop["trending_count"], prop["platform"]))
    best_over = analyzed[0]
    best_under = max(analyzed, key=lambda prop: (prop["line"], prop["trending_count"]))
    consensus = round(sum(prop["line"] for prop in analyzed) / len(analyzed), 2)
    projection = round(sum(prop["projection"] for prop in analyzed) / len(analyzed), 2)
    line_spread = round(best_under["line"] - best_over["line"], 2)
    return {
        "player": player,
        "stat": stat,
        "sport": sport_filter or "All Sports",
        "available": True,
        "message": "Lower line is better for overs; higher line is better for unders.",
        "lines": analyzed,
        "best_over": {
            "platform": best_over["platform"],
            "line": best_over["line"],
            "edge": round(projection - best_over["line"], 2),
        },
        "best_under": {
            "platform": best_under["platform"],
            "line": best_under["line"],
            "edge": round(best_under["line"] - projection, 2),
        },
        "consensus_line": consensus,
        "projection": projection,
        "line_spread": line_spread,
        "value_note": (
            f"Best over is {line_spread:g} points better than the highest posted line."
            if line_spread > 0
            else "All matching books are showing the same line."
        ),
        "no_vig": _no_vig_payload(over_odds, under_odds),
    }


def _matching_market_props(player: str, stat: str, sport_filter: str | None, platform: str) -> list[dict]:
    player_key = player.strip().lower()
    stat_key = stat.strip().lower()
    props = _fetch_props(platform, sport_filter)
    return [
        prop for prop in props
        if prop.get("player", "").strip().lower() == player_key
        and prop.get("stat", "").strip().lower() == stat_key
        and prop.get("line") is not None
    ]


def _ev_scanner_rows(
    platform: str,
    sport_filter: str | None,
    min_ev: float,
    limit: int,
    odds: int,
) -> list[dict]:
    props = _fetch_props(platform, sport_filter)
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    for prop in props:
        key = _market_group_key(prop)
        if key[0] and key[1]:
            groups.setdefault(key, []).append(prop)

    rows = []
    seen: set[tuple[str, str, str, str]] = set()
    for group in groups.values():
        best_lines = _best_line_summary_for_group(group)
        for raw in group:
            analyzed = _analyzed_feed_prop(raw)
            key = (
                analyzed["player"].strip().lower(),
                analyzed["stat"].strip().lower(),
                analyzed["sport"].strip().upper(),
                analyzed["platform"].strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            probability = max(0.0, min(100.0, float(analyzed["hit_rate"]["estimated_hit_rate"])))
            ev_percent = round(expected_value(odds, probability / 100) * 100, 2)
            if ev_percent < min_ev:
                continue
            rows.append({
                **analyzed,
                "estimated_probability": round(probability, 1),
                "assumed_odds": odds,
                "expected_value": ev_percent,
                "sportsbook_probability": round(sportsbook_probability(odds) * 100, 2),
                "best_over": best_lines["best_over"],
                "best_under": best_lines["best_under"],
                "consensus_line": best_lines["consensus_line"],
            })

    rows.sort(key=lambda row: (row["expected_value"], row["confidence"], row["edge"]), reverse=True)
    return rows[: max(1, min(limit, 100))]


def _market_timing_alert_rows(
    platform: str,
    sport_filter: str | None,
    limit: int,
    odds: int,
) -> list[dict]:
    rows = _ev_scanner_rows(platform, sport_filter, min_ev=-25.0, limit=60, odds=odds)
    alerts = [_timing_alert_from_row(row) for row in rows]
    alerts = [alert for alert in alerts if alert is not None]
    alerts.sort(key=lambda alert: (alert["priority_score"], alert["expected_value"], alert["confidence"]), reverse=True)
    return alerts[: max(1, min(limit, 25))]


def _timing_alert_from_row(row: dict) -> dict | None:
    movement = row.get("line_movement") or {}
    change = float(movement.get("change") or 0.0)
    direction = row.get("direction") or "Over"
    confidence = float(row.get("confidence") or 0.0)
    ev = float(row.get("expected_value") or 0.0)
    edge = float(row.get("edge") or 0.0)
    abs_change = abs(change)
    outlier_move = _is_outlier_line_move(float(row.get("line") or 0.0), abs_change)
    market_supports_pick = _market_move_supports_pick(direction, change)
    line_is_better_now = _line_move_improves_price(direction, change)

    if outlier_move:
        alert_type = "Large Move"
        action = "Verify before betting"
        severity = "warning"
        reason = (
            f"The line moved {abs_change:.1f}, which is large enough to verify for news, stat-label changes, "
            "or provider corrections before placing."
        )
    elif abs_change >= 1.0 and market_supports_pick and ev >= 0:
        alert_type = "Steam Move"
        action = "Take now if you still like the edge"
        severity = "urgent"
        reason = f"Market moved {movement.get('direction', 'flat')} by {abs_change:.1f}, supporting the {direction.lower()} side."
    elif ev >= 8 and confidence >= 58 and abs_change < 0.5:
        alert_type = "Take Now"
        action = "Good timing"
        severity = "positive"
        reason = "Positive EV with no major line move yet."
    elif line_is_better_now and confidence >= 52:
        alert_type = "Better Number"
        action = "Re-check news, then consider"
        severity = "watch"
        reason = f"The current line is better for {direction.lower()} than the previous snapshot."
    elif abs_change >= 1.0 and not line_is_better_now:
        alert_type = "Line Moved Against Price"
        action = "Do not chase blindly"
        severity = "warning"
        reason = f"The line is now worse for a {direction.lower()} pick than the earlier number."
    elif ev < 0 and confidence < 52:
        alert_type = "Avoid"
        action = "Pass for now"
        severity = "danger"
        reason = "Negative EV and low confidence."
    else:
        return None

    movement_score = min(abs_change, 4.0)
    priority = (
        max(ev, -10.0)
        + (confidence - 50.0) * 0.75
        + movement_score * 6.0
        + (4.0 if market_supports_pick else 0.0)
        + (3.0 if line_is_better_now else 0.0)
    )
    return {
        "type": alert_type,
        "action": action,
        "severity": severity,
        "priority_score": round(priority, 1),
        "player": row.get("player", ""),
        "sport": row.get("sport", ""),
        "platform": row.get("platform", ""),
        "game": row.get("game", ""),
        "direction": direction,
        "stat": row.get("stat", ""),
        "line": row.get("line"),
        "projection": row.get("projection"),
        "confidence": round(confidence, 1),
        "edge": round(edge, 2),
        "expected_value": round(ev, 2),
        "movement": movement,
        "market_supports_pick": market_supports_pick,
        "line_is_better_now": line_is_better_now,
        "outlier_move": outlier_move,
        "reason": reason,
    }


def _market_move_supports_pick(direction: str, change: float) -> bool:
    if abs(change) < 0.01:
        return False
    if direction == "Under":
        return change < 0
    return change > 0


def _line_move_improves_price(direction: str, change: float) -> bool:
    if abs(change) < 0.01:
        return False
    if direction == "Under":
        return change > 0
    return change < 0


def _is_outlier_line_move(current_line: float, abs_change: float) -> bool:
    if abs_change < 4.0:
        return False
    if current_line <= 0:
        return abs_change >= 6.0
    return abs_change >= max(5.0, current_line * 0.25)


def _market_group_key(prop: dict) -> tuple[str, str, str, str]:
    return (
        prop.get("player", "").strip().lower(),
        prop.get("stat", "").strip().lower(),
        prop.get("league", "").strip().upper(),
        prop.get("game", "").strip().upper(),
    )


def _best_line_summary_for_group(group: list[dict]) -> dict:
    lines = [prop for prop in group if prop.get("line") is not None]
    if not lines:
        return {"best_over": None, "best_under": None, "consensus_line": None}
    best_over = min(lines, key=lambda prop: (float(prop["line"]), -int(prop.get("trending_count") or 0)))
    best_under = max(lines, key=lambda prop: (float(prop["line"]), int(prop.get("trending_count") or 0)))
    consensus = round(sum(float(prop["line"]) for prop in lines) / len(lines), 2)
    return {
        "best_over": {
            "platform": best_over.get("platform", ""),
            "line": float(best_over["line"]),
        },
        "best_under": {
            "platform": best_under.get("platform", ""),
            "line": float(best_under["line"]),
        },
        "consensus_line": consensus,
    }


def _no_vig_payload(over_odds: int | None, under_odds: int | None) -> dict | None:
    if over_odds is None or under_odds is None:
        return None
    over_prob = sportsbook_probability(over_odds)
    under_prob = sportsbook_probability(under_odds)
    total = over_prob + under_prob
    if total <= 0:
        return None
    fair_over = over_prob / total
    fair_under = under_prob / total
    return {
        "over_probability": round(fair_over * 100, 2),
        "under_probability": round(fair_under * 100, 2),
        "over_fair_odds": _probability_to_american(fair_over),
        "under_fair_odds": _probability_to_american(fair_under),
        "hold": round((total - 1) * 100, 2),
    }


def _probability_to_american(probability: float) -> int:
    probability = max(0.0001, min(0.9999, probability))
    if probability >= 0.5:
        return round(-100 * probability / (1 - probability))
    return round(100 * (1 - probability) / probability)


def _prop_direction(line: float, projection: float | None, explicit: object = None) -> str:
    normalized = _normalize_direction(str(explicit or ""))
    if normalized in {"Over", "Under"} and explicit:
        return normalized
    if projection is None:
        return "Over"
    return "Under" if float(projection) < float(line) else "Over"


def _normalize_direction(value: str) -> str:
    text = (value or "").strip().lower()
    if text in {"under", "u", "less", "lower"}:
        return "Under"
    return "Over"


def _entry_clv_payload(entry: dict) -> dict:
    legs = [_clv_for_prop(prop) for prop in entry.get("props", [])]
    values = [leg["clv"] for leg in legs if leg["clv"] is not None]
    return {
        "id": entry["id"],
        "status": entry.get("status", ""),
        "result": entry.get("result", ""),
        "platform": entry.get("platform", ""),
        "placed_at": entry["placed_at"].isoformat() if entry.get("placed_at") else "",
        "average_clv": round(sum(values) / len(values), 2) if values else 0.0,
        "positive_legs": sum(1 for value in values if value > 0),
        "legs": legs,
    }


def _clv_for_prop(prop: dict) -> dict:
    placed_line = float(prop.get("line") or 0)
    current_line = _active_line_for_player_stat(prop.get("player", ""), prop.get("stat", ""), prop.get("platform", "PrizePicks"))
    if current_line is None:
        history = LineHistoryRepository.get_history(prop.get("player", ""), prop.get("stat", ""), prop.get("platform", "PrizePicks"))
        current_line = float(history[-1]["line"]) if history else None
    clv = round(current_line - placed_line, 2) if current_line is not None else None
    return {
        "player": prop.get("player", ""),
        "sport": prop.get("sport", ""),
        "stat": prop.get("stat", ""),
        "platform": prop.get("platform", ""),
        "placed_line": placed_line,
        "current_line": current_line,
        "clv": clv,
        "beat_market": clv is not None and clv > 0,
        "note": "Positive CLV means the over line moved higher after placement.",
    }


def _check_entry_result(entry: dict, allow_estimates: bool) -> dict:
    legs = []
    unknown = False
    source = "actual_provider"
    dnp_legs = 0

    for prop in entry["props"]:
        final_stat = _usable_final_stat_for_entry(prop, entry)
        actual = final_stat.get("actual") if final_stat else None
        status = final_stat.get("status") if final_stat else ""
        leg_source = "actual_provider"
        if status == "dnp":
            dnp_legs += 1
            leg_result = "DNP"
        elif actual is None and allow_estimates:
            actual = prop.get("projection")
            leg_source = "projection_estimate"
            if actual is None:
                unknown = True
                leg_result = "Unknown"
            leg_result = _leg_result(actual, prop["line"], prop.get("direction", "Over"))
        elif actual is None:
            unknown = True
            leg_result = "Unknown"
        elif actual is not None:
            leg_result = _leg_result(actual, prop["line"], prop.get("direction", "Over"))
        if leg_source == "projection_estimate":
            source = "projection_estimate"
        legs.append({**prop, "actual": actual, "result": leg_result, "source": leg_source})

    if unknown and dnp_legs < len(legs):
        return {
            "id": entry["id"],
            "settled": False,
            "result": "Unknown",
            "source": "unavailable",
            "message": "Final stat data is not available yet.",
            "legs": legs,
        }

    if dnp_legs == len(legs):
        result = "DNP"
    elif any(leg["result"] == "Loss" for leg in legs):
        result = "Loss"
    elif any(leg["result"] == "Push" for leg in legs):
        result = "Push"
    else:
        result = "Win"

    EntryRepository.settle(entry["id"], result, dnp_legs=dnp_legs, dnp_mode=_dnp_mode())
    return {
        "id": entry["id"],
        "settled": True,
        "result": result,
        "source": source,
        "message": "Settled from estimates." if source == "projection_estimate" else "Settled from final stats.",
        "legs": legs,
    }


def _entry_progress_payload(entry: dict) -> dict:
    legs = []
    completed = 0
    source = "unavailable"
    projected_wins = projected_losses = projected_pushes = 0

    for prop in entry["props"]:
        final_stat = _usable_final_stat_for_entry(prop, entry)
        actual = final_stat.get("actual") if final_stat else None
        status_value = final_stat.get("status") if final_stat else ""
        if status_value == "dnp":
            status = "DNP"
            projected = "Push"
            completed += 1
            source = "actual_provider"
        elif actual is None:
            status = "Pending"
            projected = _projected_leg_status(prop)
            if projected == "Win":
                projected_wins += 1
            elif projected == "Loss":
                projected_losses += 1
            elif projected == "Push":
                projected_pushes += 1
        else:
            status = _leg_result(actual, prop["line"], prop.get("direction", "Over"))
            projected = status
            completed += 1
            source = "actual_provider"

        legs.append({
            **prop,
            "actual": actual,
            "status": status,
            "final_status": status_value or ("played" if actual is not None else "pending"),
            "projected_status": projected,
            "progress_text": _leg_progress_text({**prop, "status": status}, actual),
            "progress_percent": _leg_progress_percent(prop, actual),
            "progress_label": _leg_progress_label(prop, actual),
            "clv": _clv_for_prop(prop),
        })

    live_result = _entry_result_from_leg_statuses([leg["status"] for leg in legs])
    if completed == len(legs) and legs:
        projected_result = live_result
    else:
        projected_result = _entry_result_from_leg_statuses(
            [leg["projected_status"] for leg in legs]
        )

    return {
        "id": entry["id"],
        "platform": entry["platform"],
        "wager": entry.get("wager", 0.0),
        "multiplier": entry.get("multiplier", 1.0),
        "potential_payout": entry.get("potential_payout", 0.0),
        "profit": entry.get("profit", 0.0),
        "placed_at": entry["placed_at"].isoformat() if entry.get("placed_at") else "",
        "average_confidence": entry["average_confidence"],
        "average_edge": entry["average_edge"],
        "completed_legs": completed,
        "total_legs": len(legs),
        "source": source,
        "live_result": live_result,
        "projected_result": projected_result,
        "projected_wins": projected_wins,
        "projected_losses": projected_losses,
        "projected_pushes": projected_pushes,
        "legs": legs,
    }


def _leg_result(actual: float, line: float, direction: str = "Over") -> str:
    if actual == line:
        return "Push"
    if _normalize_direction(direction) == "Under":
        return "Win" if actual < line else "Loss"
    if actual > line:
        return "Win"
    return "Loss"


def _final_stat_for_prop(prop: dict) -> dict | None:
    return find_final_stat(prop)


def _usable_final_stat_for_entry(prop: dict, entry: dict) -> dict | None:
    final_stat = _final_stat_for_prop(prop)
    if final_stat is None:
        return None

    stat_date = _parse_stat_date(final_stat.get("game_date"))
    placed_date = _entry_placed_date(entry)
    if stat_date is not None and placed_date is not None and stat_date < placed_date:
        return None

    return final_stat


def _entry_placed_date(entry: dict) -> date | None:
    placed_at = entry.get("placed_at")
    if isinstance(placed_at, datetime):
        return placed_at.date()
    if isinstance(placed_at, date):
        return placed_at
    if isinstance(placed_at, str) and placed_at.strip():
        try:
            return datetime.fromisoformat(placed_at).date()
        except ValueError:
            return None
    return None


def _parse_stat_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _projected_leg_status(prop: dict) -> str:
    projection = prop.get("projection")
    if projection is None:
        return "Pending"
    return _leg_result(projection, prop["line"], prop.get("direction", "Over"))


def _entry_result_from_leg_statuses(statuses: list[str]) -> str:
    if any(status == "Loss" for status in statuses):
        return "Loss"
    if any(status == "Pending" for status in statuses):
        return "In Progress"
    if any(status == "Push" for status in statuses):
        return "Push"
    if statuses and all(status == "DNP" for status in statuses):
        return "Push"
    return "Win" if statuses else "In Progress"


def _leg_progress_text(prop: dict, actual: float | None) -> str:
    if prop.get("status") == "DNP":
        return "Did not play"
    value = actual if actual is not None else prop.get("projection")
    label = "Actual" if actual is not None else "Projection"
    if value is None:
        return "Waiting for stat data"
    return f"{label} {value:g} vs line {prop['line']:g}"


def _leg_progress_percent(prop: dict, actual: float | None) -> float:
    line = float(prop.get("line") or 0)
    if line <= 0:
        return 0.0
    value = actual if actual is not None else prop.get("projection")
    if value is None:
        return 0.0
    return round(max(0.0, min(125.0, (float(value) / line) * 100.0)), 1)


def _leg_progress_label(prop: dict, actual: float | None) -> str:
    value = actual if actual is not None else prop.get("projection")
    if value is None:
        return "Waiting"
    prefix = "Actual" if actual is not None else "Projected"
    return f"{prefix} {float(value):g} / {float(prop.get('line') or 0):g}"


def _actual_stat_for_prop(prop: dict) -> float | None:
    return find_actual_stat(prop)


def _dnp_mode() -> str:
    mode = SettingsRepository.get("dnp_handling", "reduce")
    return mode if mode in {"reduce", "refund", "ignore"} else "reduce"


def _line_movement_payload(
    player: str,
    stat: str,
    platform: str,
    history: list[dict],
    current_line: float | None = None,
) -> dict:
    serialized = [
        {
            "line": row["line"],
            "recorded_at": row["recorded_at"].isoformat() if row.get("recorded_at") else "",
        }
        for row in history
    ]
    current = current_line if current_line is not None else (serialized[-1]["line"] if serialized else None)
    previous = _previous_line(serialized, current)
    change = round(current - previous, 2) if current is not None and previous is not None else 0.0
    if change > 0:
        direction = "up"
    elif change < 0:
        direction = "down"
    else:
        direction = "flat"
    return {
        "player": player,
        "stat": stat,
        "platform": platform,
        "current": current,
        "previous": previous,
        "change": change,
        "direction": direction,
        "snapshots": serialized,
    }


def _previous_line(serialized: list[dict], current: float | None) -> float | None:
    if current is None:
        return None
    current_groups = {
        row["recorded_at"]
        for row in serialized
        if row["line"] == current
    }
    for row in reversed(serialized):
        if row["recorded_at"] in current_groups:
            continue
        if row["line"] != current:
            return row["line"]
    return None


def _active_line_for_player_stat(player_name: str, stat: str, platform: str) -> float | None:
    props = [
        prop for prop in _fetch_props(platform, None)
        if prop.get("player", "").strip().lower() == player_name.strip().lower()
        and prop.get("stat", "").strip().lower() == stat.strip().lower()
        and prop.get("line") is not None
    ]
    if not props:
        return None
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return float(props[0]["line"])


def _entry_from_payload(payload: EntryPayload) -> Entry:
    return Entry(
        platform=_platform_from_text(payload.platform),
        props=[_prop_from_payload(prop, payload.platform) for prop in payload.props],
    )


def _prop_from_payload(payload: PropPayload, entry_platform: str) -> Prop:
    projection, auto_projected, projection_source, espn_context, source_context = _analysis_projection(payload)
    edge = calculate_edge(payload.line, projection)
    confidence, confidence_adjustment = _analysis_confidence(edge, source_context)
    return Prop(
        player=Player(name=payload.player, team=payload.team, sport=payload.sport),
        stat=_stat_from_text(payload.stat),
        line=payload.line,
        projection=projection,
        edge=edge,
        confidence=confidence,
        direction=_prop_direction(payload.line, projection, payload.direction),
        platform=_platform_from_text(payload.platform or entry_platform),
        game=payload.game,
        needs_projection=False,
        auto_projected=auto_projected,
        trending_count=payload.trending_count,
        projection_source=projection_source,
        espn_recent_average=espn_context.get("recent_average"),
        espn_hit_rate=espn_context.get("hit_rate"),
        espn_sample_size=int(espn_context.get("sample_size") or 0),
        espn_note=espn_context.get("note", ""),
        confidence_adjustment=confidence_adjustment,
        source_signals=source_context.get("signals", []),
        source_score=source_context.get("source_score", 0.0),
    )


def _analysis_projection(payload: PropPayload) -> tuple[float, bool, str, dict, dict]:
    if payload.projection is not None:
        hit_rate = estimate_hit_rate(
            payload.player,
            payload.stat,
            payload.line,
            payload.projection,
            payload.trending_count,
            payload.sport,
        )
        espn_context = _espn_context(hit_rate)
        source_context = _source_context(payload, payload.projection, espn_context, apply_projection_delta=False)
        return payload.projection, False, "user", espn_context, source_context

    model_projection = auto_projection(payload.line, payload.trending_count)
    hit_rate = estimate_hit_rate(
        payload.player,
        payload.stat,
        payload.line,
        model_projection,
        payload.trending_count,
        payload.sport,
    )
    context = _espn_context(hit_rate)
    source_context = _source_context(payload, model_projection, context, apply_projection_delta=True)
    adjustment = source_context.get("projection_delta", 0.0)
    adjusted = round(max(0.0, model_projection + adjustment), 2)
    projection_source = "multi_source_fusion" if source_context.get("signals") else "line_model"
    return adjusted, True, projection_source, context, source_context


def _espn_context(hit_rate) -> dict:
    if hit_rate.source != "final_stats":
        return {
            "source": hit_rate.source,
            "sample_size": hit_rate.sample_size,
            "hit_rate": hit_rate.estimated_hit_rate,
            "note": hit_rate.note,
        }

    history = _played_history(hit_rate.player, hit_rate.stat, sport=None, limit=10)
    recent = history[:5]
    recent_average = (
        round(sum(float(row["actual"]) for row in recent) / len(recent), 2)
        if recent
        else None
    )
    return {
        "source": "espn_final_stats",
        "sample_size": hit_rate.sample_size,
        "hit_rate": hit_rate.estimated_hit_rate,
        "last_5": hit_rate.last_5,
        "last_10": hit_rate.last_10,
        "season": hit_rate.season,
        "recent_average": recent_average,
        "note": hit_rate.note,
    }


def _played_history(player: str, stat: str, sport: str | None = None, limit: int = 10) -> list[dict]:
    return [
        row
        for row in FinalStatsRepository.history(player, stat, sport=sport, limit=limit)
        if row.get("status", "played") != "dnp"
    ]


def _analysis_confidence(edge: float, source_context: dict) -> tuple[float, float]:
    base = calculate_confidence(edge) if edge >= 0 else max(5.0, 50.0 + edge * 10.0)
    adjustment = max(-18.0, min(18.0, float(source_context.get("confidence_delta", 0.0))))
    return round(max(0.0, min(95.0, base + adjustment)), 2), round(adjustment, 2)


def _source_context(
    payload: PropPayload,
    base_projection: float,
    espn_context: dict,
    apply_projection_delta: bool,
) -> dict:
    signals: list[dict] = []
    signals.extend(_espn_form_signals(payload, base_projection, espn_context))
    signals.extend(_injury_signals(payload))
    signals.extend(_matchup_signals(payload))
    signals.extend(_line_movement_signals(payload))
    signals.extend(_platform_consensus_signals(payload))
    signals.extend(_sleeper_trending_signals(payload))
    signals.extend(_balldontlie_stat_signals(payload))
    signals.extend(_news_context_signals(payload))
    signals.extend(_weather_signals(payload))
    signals.extend(_calibration_feedback_signals(payload))

    projection_delta = sum(float(signal.get("projection_delta", 0.0)) for signal in signals) if apply_projection_delta else 0.0
    projection_delta = max(-6.0, min(6.0, projection_delta))
    confidence_delta = max(-18.0, min(18.0, sum(float(signal.get("confidence_delta", 0.0)) for signal in signals)))
    source_score = round(sum(float(signal.get("score", 0.0)) for signal in signals), 2)
    return {
        "signals": signals,
        "projection_delta": round(projection_delta, 2),
        "confidence_delta": round(confidence_delta, 2),
        "source_score": source_score,
        "sources": sorted({signal["source"] for signal in signals}),
    }


def _espn_form_signals(payload: PropPayload, base_projection: float, espn_context: dict) -> list[dict]:
    if espn_context.get("source") != "espn_final_stats" or espn_context.get("sample_size", 0) < 3:
        return []
    hit_rate = float(espn_context.get("hit_rate") or 50.0)
    recent_average = espn_context.get("recent_average")
    projection_delta = 0.0
    if recent_average is not None:
        projection_delta = (float(recent_average) - base_projection) * 0.45
    confidence_delta = max(-8.0, min(8.0, (hit_rate - 50.0) * 0.18))
    return [_signal(
        source="ESPN form",
        kind="final_stats",
        projection_delta=projection_delta,
        confidence_delta=confidence_delta,
        score=confidence_delta,
        message=f"{hit_rate:.1f}% hit rate over {espn_context.get('sample_size', 0)} played games.",
    )]


def _injury_signals(payload: PropPayload) -> list[dict]:
    try:
        injury = is_injured(payload.player, fetch_injuries(payload.sport))
    except Exception:
        injury = None
    if not injury:
        return []
    status = injury.get("status", "")
    status_lower = status.lower()
    if "out" in status_lower or "doubtful" in status_lower:
        projection_delta = -payload.line
        confidence_delta = -18.0
        score = -20.0
    elif "questionable" in status_lower or "day-to-day" in status_lower:
        projection_delta = -max(1.0, payload.line * 0.12)
        confidence_delta = -8.0
        score = -9.0
    else:
        projection_delta = -max(0.2, payload.line * 0.03)
        confidence_delta = -2.0
        score = -2.0
    return [_signal(
        source="ESPN injuries",
        kind="availability",
        projection_delta=projection_delta,
        confidence_delta=confidence_delta,
        score=score,
        message=f"{payload.player} injury status: {status}. {injury.get('detail', '')}".strip(),
    )]


def _matchup_signals(payload: PropPayload) -> list[dict]:
    if payload.sport.upper() != "WNBA" or not payload.game:
        return []
    matchup = analyze_matchup(payload.game, _stat_from_text(payload.stat))
    if matchup is None:
        return []
    projection_delta = payload.line * matchup.modifier
    confidence_delta = matchup.confidence_adjustment * 100
    return [_signal(
        source="WNBA defense",
        kind="matchup",
        projection_delta=projection_delta,
        confidence_delta=confidence_delta,
        score=confidence_delta,
        message=f"{matchup.opponent} rates as {matchup.description} for {payload.stat}.",
    )]


def _line_movement_signals(payload: PropPayload) -> list[dict]:
    history = LineHistoryRepository.get_history(
        payload.player,
        payload.stat,
        payload.platform or "PrizePicks",
    )
    movement = _line_movement_payload(payload.player, payload.stat, payload.platform or "PrizePicks", history, payload.line)
    change = float(movement.get("change") or 0.0)
    if abs(change) < 0.4:
        return []
    confidence_delta = 3.0 if change > 0 else -3.0
    return [_signal(
        source="Line movement",
        kind="market",
        projection_delta=change * 0.35,
        confidence_delta=confidence_delta,
        score=confidence_delta,
        message=f"Line moved {change:+.1f} from prior tracked snapshot.",
    )]


def _platform_consensus_signals(payload: PropPayload) -> list[dict]:
    try:
        matches = [
            prop
            for prop in _fetch_props("Both", payload.sport.upper())
            if prop.get("player", "").strip().lower() == payload.player.strip().lower()
            and prop.get("stat", "").strip().lower() == payload.stat.strip().lower()
            and prop.get("line") is not None
        ]
    except Exception:
        matches = []
    unique_platforms = {prop.get("platform", "") for prop in matches}
    if len(unique_platforms) < 2:
        return []
    lines = [float(prop["line"]) for prop in matches]
    average_line = sum(lines) / len(lines)
    difference = average_line - payload.line
    if abs(difference) < 0.2:
        confidence_delta = 2.0
        score = 2.0
        message = f"{len(unique_platforms)} platforms cluster near this line."
    else:
        confidence_delta = 4.0 if difference > 0 else -4.0
        score = confidence_delta
        message = f"{len(unique_platforms)} platforms average {average_line:.1f}, {difference:+.1f} from this line."
    return [_signal(
        source="Platform consensus",
        kind="market",
        projection_delta=difference * 0.25,
        confidence_delta=confidence_delta,
        score=score,
        message=message,
    )]


def _sleeper_trending_signals(payload: PropPayload) -> list[dict]:
    if payload.sport.upper() != "NFL":
        return []
    try:
        trend = sleeper.player_trend_signal(payload.player, payload.sport)
    except Exception:
        trend = None
    if not trend:
        return []
    net_adds = int(trend.get("net_adds") or 0)
    if abs(net_adds) < 10:
        return []
    direction = 1 if net_adds > 0 else -1
    magnitude = min(5.0, abs(net_adds) / 25.0)
    return [_signal(
        source="Sleeper trends",
        kind="fantasy_market",
        projection_delta=direction * min(1.5, magnitude * 0.25),
        confidence_delta=direction * min(4.0, magnitude),
        score=direction * min(4.0, magnitude),
        message=(
            f"Sleeper trend net {net_adds:+d} adds "
            f"({trend.get('add_count', 0)} adds, {trend.get('drop_count', 0)} drops)."
        ),
    )]


def _balldontlie_stat_signals(payload: PropPayload) -> list[dict]:
    try:
        signal = balldontlie.stat_signal(payload.player, payload.stat, payload.sport)
    except Exception:
        signal = None
    if not signal or signal.get("sample_size", 0) < 2:
        return []
    average = float(signal.get("average") or 0.0)
    difference = average - payload.line
    if abs(difference) < 0.2:
        return []
    confidence_delta = max(-5.0, min(5.0, difference * 0.8))
    return [_signal(
        source="Ball Don't Lie stats",
        kind="player_stats",
        projection_delta=difference * 0.35,
        confidence_delta=confidence_delta,
        score=confidence_delta,
        message=f"Ball Don't Lie average {average:.1f} over {signal.get('sample_size', 0)} stat rows.",
    )]


def _news_context_signals(payload: PropPayload) -> list[dict]:
    query = f'"{payload.player}" {payload.sport} {payload.team}'.strip()
    try:
        articles = newsapi.fetch_context(query, days=7, page_size=5)
    except Exception:
        articles = []
    if not articles:
        return []
    terms = newsapi.risk_terms(articles)
    if not terms:
        return [_signal(
            source="NewsAPI",
            kind="news_context",
            projection_delta=0.0,
            confidence_delta=1.0,
            score=1.0,
            message=f"{len(articles)} recent news articles found with no obvious risk terms.",
        )]
    penalty = -3.0 if any(term in terms for term in {"injury", "rest", "weather"}) else -1.0
    return [_signal(
        source="NewsAPI",
        kind="news_context",
        projection_delta=penalty * 0.25,
        confidence_delta=penalty,
        score=penalty,
        message=f"Recent news mentions possible {', '.join(terms)} context.",
    )]


def _weather_signals(payload: PropPayload) -> list[dict]:
    try:
        weather = openweather.fetch_weather_for_game(payload.game, payload.sport)
        weather_risk = openweather.weather_signal(weather)
    except Exception:
        weather_risk = None
    if not weather_risk:
        return []
    impact = float(weather_risk.get("impact") or -2.0)
    return [_signal(
        source="OpenWeather",
        kind="weather",
        projection_delta=impact * 0.25,
        confidence_delta=impact,
        score=impact,
        message=str(weather_risk.get("message", "Outdoor weather may increase variance.")),
    )]


def _calibration_feedback_signals(payload: PropPayload) -> list[dict]:
    rows = _historical_calibration_rows(payload)
    if len(rows) < 3:
        return []
    wins = sum(1 for row in rows if row["result"] == "Win")
    actual = wins / len(rows) * 100
    predicted = sum(float(row.get("predicted") or 50.0) for row in rows) / len(rows)
    edge = actual - predicted
    if abs(edge) < 4:
        return []
    confidence_delta = max(-7.0, min(8.0, edge * 0.18))
    return [_signal(
        source="Calibration feedback",
        kind="model_feedback",
        projection_delta=0.0,
        confidence_delta=confidence_delta,
        score=confidence_delta,
        message=(
            f"Historical {payload.sport}/{payload.stat} calibration is {actual:.1f}% actual "
            f"vs {predicted:.1f}% expected over {len(rows)} decisions."
        ),
    )]


def _historical_calibration_rows(payload: PropPayload) -> list[dict]:
    rows: list[dict] = []
    for bet in BetRepository().get_all():
        if bet.result not in {"Win", "Loss"}:
            continue
        sport_match = not bet.sport or bet.sport.strip().upper() == payload.sport.strip().upper()
        stat_match = not bet.stat_type or bet.stat_type.strip().lower() == payload.stat.strip().lower()
        platform_match = not bet.platform or bet.platform.strip().lower() == (payload.platform or "").strip().lower()
        if sport_match and (stat_match or platform_match):
            rows.append({
                "result": bet.result,
                "predicted": float(bet.win_probability or 50.0),
            })

    for entry in EntryRepository.all():
        if entry.get("status") != "Settled" or entry.get("result") not in {"Win", "Loss"}:
            continue
        props = entry.get("props") or []
        sport_match = any(str(prop.get("sport", "")).upper() == payload.sport.strip().upper() for prop in props)
        stat_match = any(str(prop.get("stat", "")).lower() == payload.stat.strip().lower() for prop in props)
        platform_match = str(entry.get("platform", "")).lower() == (payload.platform or "").strip().lower()
        if sport_match and (stat_match or platform_match):
            rows.append({
                "result": entry["result"],
                "predicted": float(entry.get("average_confidence") or 50.0),
            })

    if len(rows) >= 3:
        return rows

    global_rows = [
        {"result": bet.result, "predicted": float(bet.win_probability or 50.0)}
        for bet in BetRepository().get_all()
        if bet.result in {"Win", "Loss"}
    ]
    global_rows.extend(
        {"result": entry["result"], "predicted": float(entry.get("average_confidence") or 50.0)}
        for entry in EntryRepository.all()
        if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss"}
    )
    return global_rows if len(global_rows) >= 8 else rows


def _signal(
    source: str,
    kind: str,
    projection_delta: float,
    confidence_delta: float,
    score: float,
    message: str,
) -> dict:
    return {
        "source": source,
        "kind": kind,
        "projection_delta": round(projection_delta, 2),
        "confidence_delta": round(confidence_delta, 2),
        "score": round(score, 2),
        "message": message,
    }


def _entry_analysis(entry: Entry) -> dict:
    result = entry_recommendation(entry)
    risk = calculate_entry_risk(entry.props)
    warnings = detect_correlations(entry)
    espn_notes = _entry_espn_notes(entry.props)
    return {
        "entry": _serialize_entry(entry),
        "recommendation": result,
        "risk": {
            "level": risk.risk.value,
            "average_confidence": round(risk.average_confidence, 2),
            "average_edge": round(risk.average_edge, 2),
            "prop_count": risk.prop_count,
        },
        "warnings": warnings + espn_notes,
        "espn_context": {
            "props_with_history": sum(1 for prop in entry.props if prop.espn_sample_size > 0),
            "average_hit_rate": _average_espn_hit_rate(entry.props),
            "source": "ESPN final stats via imported box scores",
        },
        "source_fusion": _source_fusion_summary(entry.props),
    }


def _entry_espn_notes(props: list[Prop]) -> list[str]:
    notes = []
    for prop in props:
        if prop.espn_sample_size == 0:
            continue
        direction = "supports" if (prop.espn_hit_rate or 0) >= 55 else "questions"
        notes.append(
            f"ESPN form {direction} {prop.player.name} {prop.stat.value}: "
            f"{prop.espn_hit_rate:.1f}% hit rate over {prop.espn_sample_size} games."
        )
    return notes


def _average_espn_hit_rate(props: list[Prop]) -> float:
    rates = [prop.espn_hit_rate for prop in props if prop.espn_hit_rate is not None and prop.espn_sample_size > 0]
    return round(sum(rates) / len(rates), 1) if rates else 0.0


def _source_fusion_summary(props: list[Prop]) -> dict:
    signals = [signal for prop in props for signal in (prop.source_signals or [])]
    return {
        "signal_count": len(signals),
        "sources": sorted({signal["source"] for signal in signals}),
        "average_source_score": round(sum(prop.source_score for prop in props) / len(props), 2) if props else 0.0,
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
        "direction": prop.direction,
        "edge": round(prop.edge, 2),
        "confidence": round(prop.confidence, 2),
        "platform": prop.platform.value,
        "game": prop.game,
        "auto_projected": prop.auto_projected,
        "trending_count": prop.trending_count,
        "projection_source": prop.projection_source,
        "espn": {
            "recent_average": prop.espn_recent_average,
            "hit_rate": prop.espn_hit_rate,
            "sample_size": prop.espn_sample_size,
            "note": prop.espn_note,
            "confidence_adjustment": prop.confidence_adjustment,
        },
        "source_signals": prop.source_signals or [],
        "source_score": prop.source_score,
    }


def _serialize_suggestion(suggestion) -> dict:
    leg_count = suggestion.entry.prop_count
    return {
        "rank": suggestion.rank,
        "score": suggestion.score,
        "grade": suggestion.grade,
        "action": suggestion.action,
        "leg_count": leg_count,
        "risk_tier": "Higher Risk" if leg_count >= 4 else "Standard",
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
    compact = normalized.replace("-", " ").replace("_", " ")
    if "h+r+rbi" in compact or "hits+runs+rbis" in compact or "hit run rbi" in compact:
        return StatType.HITS_RUNS_RBIS
    if "pitcher" in compact and ("strikeout" in compact or compact.strip() == "ks"):
        return StatType.PITCHER_STRIKEOUTS
    if "strikeout" in compact or compact.strip() in {"ks", "k"}:
        return StatType.STRIKEOUTS
    if "passing" in compact and "yard" in compact:
        return StatType.PASSING_YARDS
    if "rushing" in compact and "yard" in compact:
        return StatType.RUSHING_YARDS
    if "receiving" in compact and "yard" in compact:
        return StatType.RECEIVING_YARDS
    if "reception" in compact:
        return StatType.RECEPTIONS
    if "shot" in compact and "goal" in compact:
        return StatType.SHOTS_ON_GOAL
    if "shot" in compact and "target" in compact:
        return StatType.SHOTS_ON_TARGET
    if "home run" in compact or compact.strip() == "hr":
        return StatType.HOME_RUNS
    if "total base" in compact:
        return StatType.TOTAL_BASES
    if "rbi" in compact:
        return StatType.RBIS
    for stat in StatType:
        stat_text = stat.value.lower()
        if stat_text == compact or stat_text in compact:
            return stat
    if "hit" in compact:
        return StatType.HITS
    if "point" in compact:
        return StatType.POINTS
    if "rebound" in compact:
        return StatType.REBOUNDS
    if "assist" in compact:
        return StatType.ASSISTS
    if "pra" in compact:
        return StatType.PRA
    return StatType.POINTS
