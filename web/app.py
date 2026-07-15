from __future__ import annotations

import os
import csv
import json
import base64
import hashlib
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone, timedelta
from io import StringIO
from pathlib import Path
from typing import Literal

import data.providers.prizepicks as prizepicks
import data.providers.underdog as underdog
import data.providers.sleeper as sleeper
import data.providers.sportsdataio as sportsdataio
import data.providers.nba_summer_league as nba_summer_league
import data.providers.balldontlie as balldontlie
import data.providers.newsapi as newsapi
import data.providers.openweather as openweather
from data.providers.generic_props import normalize_props
from data.providers.prop_filters import is_combined_player_prop
from data.providers.espn import (
    refresh_final_stats_for_entries,
    refresh_game_times_for_entries,
    refresh_live_stats_for_entries,
)
import requests
from dotenv import load_dotenv
from analytics.backtesting import backtest_summary
from analytics.hit_rate import estimate_hit_rate
from analytics.correlation import detect_correlations
from analytics.edgeiq_model import MODEL_VERSION as EDGEIQ_LOCAL_MODEL_VERSION
from analytics.edgeiq_model import compose_parlay_response as local_parlay_response
from analytics.edgeiq_model import model_card as local_model_card
from analytics.entry_recommendation import recommendation as entry_recommendation
from analytics.entry_suggestions import suggest_entries
from analytics.ev import expected_value, sportsbook_probability
from analytics.kelly import breakeven_probability, half_kelly, kelly_fraction, suggested_wager
from analytics.projection import auto_projection
from analytics.prop_metrics import calculate_confidence, calculate_edge
from analytics.risk import calculate_entry_risk
from analytics.recommendation import recommendation as ev_recommendation
from analytics.defense_vs_position import analyze_matchup
from fastapi import BackgroundTasks, FastAPI, HTTPException
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
from utils.stat_normalization import stat_type_from_text
from utils.time import iso_utc, utc_now


load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"
STATIC_ASSET_VERSION = "20260715-trust-polish"
DAILY_BRIEFING_CACHE_VERSION = 6
DAILY_BRIEFING_CACHE_TTL_HOURS = 10
DAILY_SCAN_STATUS_KEY = "daily_briefing_scan_status"
DAILY_SCAN_LOG_KEY = "daily_briefing_run_log"
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
ENTRY_PLATFORMS = ("PrizePicks", "Underdog", "Sleeper")
CONTEXT_PLATFORMS = ("Ball Don't Lie",)
PROP_PLATFORMS = (*ENTRY_PLATFORMS, *CONTEXT_PLATFORMS)
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


@app.get("/api/version")
def version() -> dict:
    return {
        "app": "EdgeIQ Web",
        "ui_asset_version": STATIC_ASSET_VERSION,
        "capabilities": [
            "advantage_center",
            "paper_entries",
            "provider_health",
            "watchlist",
            "boost_analysis",
        ],
    }


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


class UserPreferencePayload(BaseModel):
    risk_style: Literal["conservative", "balanced", "aggressive"] = "balanced"
    preferred_legs: Literal["2", "3", "2-3", "2-5"] = "2-3"
    allow_high_risk: bool = True
    avoid_same_game: bool = True
    max_wager_pct: float = Field(default=5.0, ge=0.1, le=100)
    default_platform: str = "PrizePicks"
    default_sport: str = "All Sports"
    display_name: str = "Joshua"


class ProviderWeightsPayload(BaseModel):
    weights: dict[str, float]


class RefreshSchedulePayload(BaseModel):
    morning_scan: str = "08:00"
    injury_refresh: str = "11:00"
    line_snapshots: str = "*/30"
    result_check: str = "23:30"
    nightly_calibration: str = "02:00"
    enabled: bool = True


class BankrollStrategyPayload(BaseModel):
    mode: Literal["flat", "conservative", "balanced", "aggressive", "kelly", "paper"] = "balanced"
    unit_size: float = Field(default=10.0, ge=0)
    max_wager_pct: float = Field(default=5.0, ge=0.1, le=100)
    paper_first: bool = False


class WatchlistItemPayload(BaseModel):
    player: str
    sport: str = "All Sports"
    stat: str = ""
    platform: str = "PrizePicks"
    direction: Literal["Over", "Under", "Any"] = "Any"
    target_line: float | None = None
    alert_when: Literal["at_or_better", "moves_by", "available"] = "at_or_better"
    move_threshold: float = Field(default=1.0, ge=0)
    note: str = ""


class BoostAnalysisPayload(BaseModel):
    player: str
    sport: str
    stat: str
    platform: str = "PrizePicks"
    direction: Literal["Over", "Under"] = "Over"
    original_line: float
    boosted_line: float
    odds: int = -110


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


@app.get("/api/settings/preferences")
def user_preferences() -> dict:
    return _user_preferences()


@app.post("/api/settings/preferences")
def update_user_preferences(payload: UserPreferencePayload) -> dict:
    prefs = payload.model_dump()
    SettingsRepository.set("user_preferences", json.dumps(prefs))
    return {"preferences": prefs}


@app.get("/api/settings/bankroll-strategy")
def bankroll_strategy() -> dict:
    return {"strategy": _bankroll_strategy()}


@app.post("/api/settings/bankroll-strategy")
def update_bankroll_strategy(payload: BankrollStrategyPayload) -> dict:
    strategy = payload.model_dump()
    SettingsRepository.set("bankroll_strategy", json.dumps(strategy))
    return {"strategy": _bankroll_strategy()}


@app.get("/api/settings/provider-weights")
def provider_weights() -> dict:
    return {"weights": _provider_weights()}


@app.post("/api/settings/provider-weights")
def update_provider_weights(payload: ProviderWeightsPayload) -> dict:
    weights = {
        key: max(0.0, min(2.0, float(value)))
        for key, value in payload.weights.items()
        if str(key).strip()
    }
    merged = {**_provider_weights(), **weights}
    SettingsRepository.set("provider_weights", json.dumps(merged))
    return {"weights": merged}


@app.get("/api/data-health")
def data_health() -> dict:
    return _data_health_payload()


@app.get("/api/providers/sleeper/status")
def sleeper_status() -> dict:
    return sleeper.public_api_status()


@app.get("/api/automation/refresh-schedule")
def refresh_schedule() -> dict:
    return _refresh_schedule_payload()


@app.post("/api/automation/refresh-schedule")
def update_refresh_schedule(payload: RefreshSchedulePayload) -> dict:
    schedule = payload.model_dump()
    SettingsRepository.set("refresh_schedule", json.dumps(schedule))
    return {"schedule": schedule}


@app.post("/api/automation/run-daily-refresh")
def run_daily_refresh() -> dict:
    result = run_sync()
    ran_at = utc_now()
    SettingsRepository.set("last_daily_refresh", iso_utc(ran_at))
    prefs = _user_preferences()
    platform = prefs.get("default_platform", "PrizePicks")
    sport = prefs.get("default_sport", "All Sports")
    sport_filter = None if sport == "All Sports" else str(sport).upper()
    scan = _run_daily_briefing_scan(platform, sport_filter, trigger="daily_refresh", sync_result=result)
    return {
        "ran_at": iso_utc(ran_at),
        "result": result,
        "schedule": _refresh_schedule_payload(),
        "daily_briefing": scan.get("cache", {}),
        "scan": scan,
    }


@app.get("/api/notifications")
def notifications() -> dict:
    return _notification_payload()


@app.get("/api/players/{player_name}/availability")
def player_availability(player_name: str, sport: str = "WNBA", team: str = "", game: str = "") -> dict:
    return _player_availability_payload(player_name, sport, team, game)


@app.get("/api/watchlist")
def watchlist() -> dict:
    return {"items": _watchlist_items(), "alerts": _watchlist_alerts()}


@app.post("/api/watchlist")
def save_watchlist_item(payload: WatchlistItemPayload) -> dict:
    item = payload.model_dump()
    item["id"] = _watchlist_item_id(item)
    items = [row for row in _watchlist_items() if row.get("id") != item["id"]]
    items.append(item)
    SettingsRepository.set("prop_watchlist", json.dumps(items))
    return {"items": items, "alerts": _watchlist_alerts(items)}


@app.delete("/api/watchlist/{item_id}")
def delete_watchlist_item(item_id: str) -> dict:
    items = [row for row in _watchlist_items() if row.get("id") != item_id]
    SettingsRepository.set("prop_watchlist", json.dumps(items))
    return {"items": items, "alerts": _watchlist_alerts(items)}


@app.get("/api/watchlist/alerts")
def watchlist_alerts() -> dict:
    alerts = _watchlist_alerts()
    return {"alerts": alerts, "count": len(alerts)}


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


@app.get("/api/props/confirmed")
def confirmed_props(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    limit: int = 20,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _confirmed_props_payload(platform, sport_filter, limit)


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


@app.get("/api/daily-briefing")
def daily_briefing(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
    refresh: bool = False,
    cached_only: bool = False,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _cached_daily_briefing_payload(platform, sport_filter, refresh=refresh, cached_only=cached_only)


@app.post("/api/daily-briefing/scan")
def start_daily_briefing_scan(
    background_tasks: BackgroundTasks,
    platform: str = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    scan = _new_daily_scan(platform, sport_filter, trigger="manual")
    _save_daily_scan_status(scan)
    background_tasks.add_task(_run_daily_briefing_scan, platform, sport_filter, scan["id"], "manual")
    return scan


@app.get("/api/daily-briefing/scan-status")
def daily_briefing_scan_status(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _daily_scan_status_payload(platform, sport_filter)


@app.get("/api/dashboard/advantage-center")
def advantage_center(
    platform: str = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _advantage_center_payload(platform, sport_filter)


@app.post("/api/ai/parlay-chat")
def ai_parlay_chat(payload: ParlayChatPayload) -> dict:
    request = _parse_parlay_request(payload.message, payload.sport)
    suggestions, search = _parlay_chat_suggestions(payload.platform, request)
    if not suggestions:
        suggestions, search = _parlay_chat_suggestions(
            payload.platform,
            {**request, "confirmed_only": False, "risk_profile": "balanced"},
            relaxed=True,
        )
    serialized = [_serialize_suggestion(suggestion) for suggestion in suggestions]
    local_message, local_pick = local_parlay_response(serialized, request)
    ai_text, ai_error = _openai_parlay_response(payload.message, serialized, request)
    selected = local_pick.suggestion if local_pick else (serialized[0] if serialized else None)
    return {
        "message": ai_text or local_message,
        "suggestion": selected,
        "candidates": serialized,
        "alternatives": [candidate for candidate in serialized if candidate is not selected][:3],
        "ai_enabled": ai_text is not None,
        "model": _openai_model() if ai_text else EDGEIQ_LOCAL_MODEL_VERSION,
        "local_model": {
            **local_model_card(serialized),
            "selected_score": local_pick.score if local_pick else 0.0,
            "reasons": local_pick.reasons if local_pick else [],
            "cautions": local_pick.cautions if local_pick else [],
        },
        "ai_error": ai_error,
        "request": request,
        "search": search,
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
        "local_model": {
            "available": True,
            "model": EDGEIQ_LOCAL_MODEL_VERSION,
            "purpose": "Offline parlay ranking and recommendation fallback.",
        },
        "note": (
            "OpenAI key is present and has the expected prefix."
            if key.startswith("sk-")
            else "OpenAI key is missing or invalid; EdgeIQ Local remains available for recommendations."
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
        "model": _openai_model() if ai_text else EDGEIQ_LOCAL_MODEL_VERSION,
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


@app.get("/api/games/context")
def game_context(
    game: str,
    sport: str = "All Sports",
    platform: str = "Both",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return _game_context_payload(game, sport_filter, platform)


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


@app.post("/api/market/boost-analysis")
def boost_analysis(payload: BoostAnalysisPayload) -> dict:
    return _boost_analysis_payload(payload)


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
    min_confidence: float = 0.0,
    min_ev: float = -25.0,
    alert_type: str = "All",
    hide_outliers: bool = False,
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    rows = _market_timing_alert_rows(platform, sport_filter, limit, odds, min_confidence, min_ev, alert_type, hide_outliers)
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
    live_stats = _refresh_live_stats(EntryRepository.pending())
    return {
        "default_wagers": default_wagers,
        "final_stats_file": final_stats_file,
        "bet_history_file": bet_history_file,
        "auto_check": auto_check,
        "live_stats": live_stats,
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
    game_time: str = ""
    season_type: str = ""
    trending_count: int = 0


class EntryPayload(BaseModel):
    platform: str = "PrizePicks"
    wager: float = Field(default=0.0, ge=0)
    multiplier: float = Field(default=1.0, ge=1)
    recommended_by_app: bool = False
    entry_mode: Literal["real", "paper"] = "real"
    props: list[PropPayload]


class AutoPaperCalibrationPayload(BaseModel):
    platform: str = "PrizePicks"
    sport: str = "All Sports"
    leg_count: int = Field(default=2, ge=2, le=5)
    max_entries: int = Field(default=3, ge=1, le=10)
    prefer_confirmed: bool = True
    dry_run: bool = False


class AiEntryReviewPayload(EntryPayload):
    question: str = "Should I place this entry?"


@app.post("/api/entries/analyze")
def analyze_entry(payload: EntryPayload) -> dict:
    _reject_combined_player_props(payload.props)
    entry = _entry_from_payload(payload)
    return _entry_analysis(entry, payload)


@app.post("/api/entries/placement-check")
def placement_check(payload: EntryPayload) -> dict:
    _reject_combined_player_props(payload.props)
    return _placement_check(payload)


@app.post("/api/entries/place")
def place_entry(payload: EntryPayload) -> dict:
    _reject_combined_player_props(payload.props)
    if payload.entry_mode == "real" and payload.wager <= 0:
        raise HTTPException(status_code=400, detail="Enter an amount wagered before placing the entry.")
    entry = _entry_from_payload(payload)
    analysis = _entry_analysis(entry, payload)
    hard_blocks = [guard for guard in analysis.get("risk_guardrails", []) if guard.get("severity") == "danger"]
    if hard_blocks:
        raise HTTPException(status_code=400, detail="Risk guardrail blocked placement: " + hard_blocks[0]["message"])
    entry_id = EntryRepository.save(
        entry,
        status="Pending",
        wager=payload.wager,
        multiplier=payload.multiplier,
        recommended_by_app=payload.recommended_by_app,
        audit_snapshot=json.dumps(_entry_audit_snapshot(entry, payload, analysis)),
        entry_mode=payload.entry_mode,
    )
    return {
        "id": entry_id,
        "status": "Pending",
        "entry_mode": payload.entry_mode,
        "analysis": analysis,
        "dashboard": get_dashboard(),
    }


@app.post("/api/entries/auto-paper-calibration")
def auto_paper_calibration(payload: AutoPaperCalibrationPayload) -> dict:
    return _auto_paper_calibration(payload)


@app.get("/api/entries/pending")
def pending_entries() -> dict:
    return {"entries": [_serialize_pending(entry) for entry in EntryRepository.pending()]}


@app.get("/api/entries/progress")
def entry_progress(auto_check: bool = False, refresh_providers: bool = True, market_detail: bool = True) -> dict:
    auto_check_result = None
    if auto_check:
        auto_check_result = _auto_check_pending_entries(
            allow_estimates=False,
            refresh_providers=refresh_providers,
        )
    pending = EntryRepository.pending()
    live_stats_sync = (
        _refresh_live_stats(pending)
        if pending and refresh_providers
        else {"provider": "espn_live", "skipped": True, "imported": 0, "fetched_rows": 0, "errors": []}
    )
    game_time_sync = (
        _backfill_missing_game_times(pending)
        if pending and refresh_providers
        else {"provider": "espn", "skipped": True, "updated": 0, "fetched_rows": 0, "errors": []}
    )
    if game_time_sync.get("updated") or live_stats_sync.get("imported"):
        pending = EntryRepository.pending()
    entries = [_entry_progress_payload(entry, include_market_detail=market_detail) for entry in pending]
    return {
        "entries": entries,
        "active": len(entries),
        "with_live_stats": sum(1 for entry in entries if _entry_has_stat_data(entry)),
        "auto_check": auto_check_result,
        "game_time_sync": game_time_sync,
        "live_stats_sync": live_stats_sync,
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
    platform_pairs = _props_by_platform(platform)
    suggestions = []
    if leg_count == 2:
        for platform_model, raw_props in platform_pairs:
            suggestions.extend(_mixed_risk_suggestions(raw_props, sport, platform_model))
        mode = "balanced_with_higher_risk"
    else:
        for platform_model, raw_props in platform_pairs:
            suggestions.extend(suggest_entries(raw_props, sport, platform_model, leg_count=leg_count))
        mode = f"{leg_count}_leg"
    return {
        "suggestions": [_serialize_suggestion(suggestion) for suggestion in suggestions],
        "mode": mode,
    }


@app.get("/api/entries/confirmed-suggestions")
def confirmed_entry_suggestions(
    sport: str = "WNBA",
    platform: str = "PrizePicks",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    payload = _confirmed_props_payload(platform, sport_filter, limit=80)
    suggestion_sport = sport if sport != "All Sports" else payload["sport"]
    suggestions = _mixed_risk_suggestions(payload["raw_props"], suggestion_sport, _entry_platform_from_text(platform))
    return {
        "suggestions": [_serialize_suggestion(suggestion) for suggestion in suggestions],
        "confirmed_count": payload["count"],
        "platform": platform,
        "sport": sport,
        "mode": "confirmed_props_top_5",
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


@app.get("/api/analytics/personal-profile")
def personal_profile() -> dict:
    return _personal_profile_payload()


@app.post("/api/entries/auto-check")
def auto_check_entries(allow_estimates: bool = False, refresh_providers: bool = True) -> dict:
    return _auto_check_pending_entries(allow_estimates, refresh_providers=refresh_providers)


@app.post("/api/entries/backfill-final-stats")
def backfill_entry_final_stats(allow_estimates: bool = True) -> dict:
    entries = [
        entry for entry in EntryRepository.all()
        if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss", "Push", "DNP"}
    ]
    backfilled = 0
    leg_rows = 0
    estimated = 0
    for entry in entries:
        legs = _entry_leg_final_snapshots(entry, allow_estimates=allow_estimates)
        if not legs:
            continue
        EntryRepository.store_settled_leg_results(entry["id"], legs)
        backfilled += 1
        leg_rows += len(legs)
        estimated += sum(1 for leg in legs if leg.get("source") == "projection_estimate")
    return {
        "entries": len(entries),
        "backfilled": backfilled,
        "leg_rows": leg_rows,
        "estimated_leg_rows": estimated,
    }


def _auto_check_pending_entries(allow_estimates: bool = False, refresh_providers: bool = True) -> dict:
    pending_entries = EntryRepository.pending()
    refresh = (
        _refresh_final_stats(pending_entries)
        if pending_entries and refresh_providers
        else {"provider": "local_cache", "skipped": not refresh_providers, "imported": 0, "errors": []}
    )
    checks = [_check_entry_result(entry, allow_estimates) for entry in pending_entries]
    settled = [check for check in checks if check["settled"]]
    return {
        "checked": len(checks),
        "settled": len(settled),
        "entries": checks,
        "estimated": any(check["source"] == "projection_estimate" for check in checks),
        "final_stats_refresh": refresh,
    }


def _entry_leg_final_snapshots(entry: dict, allow_estimates: bool) -> list[dict]:
    legs = []
    for prop in entry.get("props", []):
        final_stat = _usable_final_stat_for_entry(prop, entry)
        actual = final_stat.get("actual") if final_stat else None
        status = str(final_stat.get("status") if final_stat else "").strip().lower()
        source = str(final_stat.get("source") if final_stat else "").strip() or "actual_provider"
        final_status = status or ("played" if actual is not None else "unknown")
        if status == "dnp":
            result = "DNP"
        elif actual is None and allow_estimates:
            actual = prop.get("projection")
            source = "projection_estimate"
            final_status = "estimated"
            result = _leg_result(actual, prop["line"], prop.get("direction", "Over")) if actual is not None else "Unknown"
        elif actual is None:
            result = "Unknown"
        else:
            result = _leg_result(actual, prop["line"], prop.get("direction", "Over"))
        legs.append({**prop, "actual": actual, "result": result, "source": source, "final_status": final_status})
    return legs


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
    EntryRepository.sync_settled_to_bet_history()
    entries = [
        _serialize_bet_history_entry(entry)
        for entry in EntryRepository.all()
        if entry.get("status") == "Settled"
    ]
    return {
        "bets": [_serialize_bet(bet) for bet in BetRepository().get_all(include_synced_entries=True)],
        "entries": entries,
    }


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
        "monthly_profit": stats.get("monthly_profit", {}),
        "summary": stats,
    }


@app.get("/api/analytics/backtest")
def backtest() -> dict:
    return backtest_summary(BetRepository().get_all(), EntryRepository.all())


@app.post("/api/analytics/refresh-calibration-data")
def refresh_calibration_data() -> dict:
    entries = EntryRepository.all()
    provider_refresh = _refresh_final_stats(entries)
    backfill = _backfill_settled_entry_leg_results(entries)
    return {
        "provider_refresh": provider_refresh,
        "backfill": backfill,
        "backtest": backtest_summary(BetRepository().get_all(), EntryRepository.all()),
    }


@app.get("/api/analytics/model-health")
def model_health() -> dict:
    return _model_health_payload()


@app.get("/api/analytics/accuracy-lab")
def accuracy_lab() -> dict:
    return _accuracy_lab_payload()


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
                    source=source or "imported",
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
    return [
        prop for prop in props
        if _is_actionable_provider_prop(prop)
    ]


def _is_actionable_provider_prop(prop: dict) -> bool:
    player = str(prop.get("player") or "").strip()
    line = prop.get("line")
    if not player or player.lower() == "unknown" or line is None:
        return False
    return not is_combined_player_prop(prop) and not _is_season_long_prop(prop)


def _is_season_long_prop(prop: dict | PropPayload) -> bool:
    season_type = str(_prop_value(prop, "season_type") or "").strip().lower()
    stat = str(_prop_value(prop, "stat") or "").strip().lower()
    game = str(_prop_value(prop, "game") or "").strip().lower()
    return season_type == "season_long" or stat.startswith("season ") or game in {"season", "season long", "season-long"}


def _prop_value(prop: dict | PropPayload, key: str):
    if isinstance(prop, dict):
        return prop.get(key)
    return getattr(prop, key, None)


def _selected_platforms(platform: str) -> list[str]:
    canonical = _canonical_platform(platform)
    if canonical == "Both":
        return list(ENTRY_PLATFORMS)
    return [canonical] if canonical in PROP_PLATFORMS else ["PrizePicks"]


def _selected_entry_platforms(platform: str) -> list[str]:
    canonical = _canonical_platform(platform)
    if canonical == "Both":
        return list(ENTRY_PLATFORMS)
    return [canonical] if canonical in ENTRY_PLATFORMS else ["PrizePicks"]


def _entry_platform_from_text(value: str) -> Platform:
    canonical = _canonical_platform(value)
    if canonical not in ENTRY_PLATFORMS:
        canonical = "PrizePicks"
    return _platform_from_text(canonical)


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
    summer_league_refresh = nba_summer_league.refresh_final_stats_for_entries(pending_entries)
    imported = (
        espn_refresh.get("imported", 0)
        + sportsdataio_refresh.get("imported", 0)
        + summer_league_refresh.get("imported", 0)
    )
    fetched_rows = (
        espn_refresh.get("fetched_rows", 0)
        + sportsdataio_refresh.get("fetched_rows", 0)
        + summer_league_refresh.get("fetched_rows", 0)
    )
    return {
        "providers": ["espn", "sportsdataio", "nba_summer_league"],
        "provider": "espn+sportsdataio+nba_summer_league",
        "espn": espn_refresh,
        "sportsdataio": sportsdataio_refresh,
        "nba_summer_league": summer_league_refresh,
        "imported": imported,
        "fetched_rows": fetched_rows,
        "errors": (
            espn_refresh.get("errors", [])
            + sportsdataio_refresh.get("errors", [])
            + summer_league_refresh.get("errors", [])
        ),
    }


def _refresh_live_stats(pending_entries: list[dict]) -> dict:
    if not pending_entries:
        return {"provider": "espn_live", "skipped": True, "imported": 0, "fetched_rows": 0, "errors": []}
    return refresh_live_stats_for_entries(pending_entries)


def _backfill_settled_entry_leg_results(entries: list[dict]) -> dict:
    backfilled = 0
    leg_rows = 0
    provider_rows = 0
    for entry in entries:
        if entry.get("status") != "Settled":
            continue
        legs = _entry_leg_final_snapshots(entry, allow_estimates=False)
        resolved = [leg for leg in legs if leg.get("result") in {"Win", "Loss", "Push", "DNP"}]
        if not resolved:
            continue
        EntryRepository.store_settled_leg_results(entry["id"], legs)
        backfilled += 1
        leg_rows += len(legs)
        provider_rows += sum(1 for leg in resolved if leg.get("source") != "projection_estimate")
    return {
        "entries": len([entry for entry in entries if entry.get("status") == "Settled"]),
        "backfilled": backfilled,
        "leg_rows": leg_rows,
        "provider_rows": provider_rows,
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
        dates = [datetime.now(timezone.utc).date()]
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

    risk_profile = "balanced"
    if any(token in text for token in (" SAFE ", " SAFER ", " CONSERVATIVE ", " LOW RISK ", " CHALKY ")):
        risk_profile = "safe"
    elif any(token in text for token in (" AGGRESSIVE ", " HIGH RISK ", " LONGSHOT ", " LOTTO ", " SPICY ")):
        risk_profile = "aggressive"

    confirmed_only = any(
        token in text
        for token in (" CONFIRMED ", " VERIFIED ", " LIVE BOARD ", " CURRENT BOARD ", " REAL LINES ")
    )

    return {
        "leg_count": leg_count,
        "sport": sport,
        "sport_label": sport or "All Sports",
        "risk_profile": risk_profile,
        "confirmed_only": confirmed_only,
    }


def _auto_paper_calibration(payload: AutoPaperCalibrationPayload) -> dict:
    entries = EntryRepository.all()
    backtest_data = backtest_summary(BetRepository().get_all(), entries)
    targets = _calibration_learning_targets(backtest_data, payload.sport)
    existing_signatures = {
        _entry_signature(entry)
        for entry in EntryRepository.pending()
        if str(entry.get("entry_mode", "real")).lower() == "paper"
    }
    created = []
    skipped = []

    for target in targets:
        if len(created) >= payload.max_entries:
            break
        suggestions = _paper_calibration_suggestions(payload, target)
        if not suggestions:
            skipped.append({**target, "reason": "No current props matched this calibration target."})
            continue

        for suggestion in suggestions:
            if len(created) >= payload.max_entries:
                break
            serialized = _serialize_suggestion(suggestion)
            signature = _entry_signature(serialized["entry"])
            if signature in existing_signatures:
                skipped.append({**target, "reason": "A matching pending paper entry already exists."})
                continue
            audit = _paper_calibration_audit(serialized, target, backtest_data, payload)
            entry_id = None
            if not payload.dry_run:
                entry_id = EntryRepository.save(
                    suggestion.entry,
                    status="Pending",
                    wager=0.0,
                    multiplier=1.0,
                    recommended_by_app=True,
                    audit_snapshot=json.dumps(audit),
                    entry_mode="paper",
                )
                existing_signatures.add(signature)
            created.append({
                "id": entry_id,
                "target": target,
                "suggestion": serialized,
                "audit": audit,
                "status": "preview" if payload.dry_run else "Pending",
                "entry_mode": "paper",
            })

    return {
        "created": created,
        "created_count": len(created),
        "dry_run": payload.dry_run,
        "targets": targets,
        "skipped": skipped,
        "dashboard": get_dashboard() if not payload.dry_run else None,
    }


def _calibration_learning_targets(backtest_data: dict, selected_sport: str) -> list[dict]:
    targets: list[dict] = []
    sport = None if selected_sport == "All Sports" else selected_sport.upper()
    if sport:
        targets.append({
            "type": "Sport",
            "name": sport,
            "sport": sport,
            "priority": 110,
            "reason": f"User-selected sport {sport} needs paper calibration samples.",
        })

    for segment in backtest_data.get("what_fails", []):
        segment_type = segment.get("type", "")
        name = str(segment.get("name", "")).strip()
        if not name or segment_type not in {"Sport", "Stat", "Platform", "Confidence"}:
            continue
        target = {
            "type": segment_type,
            "name": name,
            "sport": name.upper() if segment_type == "Sport" and name.upper() in SUPPORTED_SPORTS else sport,
            "priority": 100 - min(60, int(segment.get("tracked") or 0) * 4),
            "reason": f"{segment_type} {name} is underperforming: {segment.get('win_rate', 0)}% win rate, {segment.get('roi', 0)}% ROI.",
        }
        targets.append(target)

    for bucket in backtest_data.get("calibration", []):
        bets = int(bucket.get("bets") or 0)
        error = abs(float(bucket.get("error") or 0.0))
        if bets >= 4 and error < 12:
            continue
        targets.append({
            "type": "Confidence",
            "name": bucket.get("label", "Unknown"),
            "sport": sport,
            "priority": 80 + int(error) - min(20, bets * 3),
            "reason": f"Confidence bucket {bucket.get('label', 'Unknown')} has {bets} samples and {error:.1f} pts calibration error.",
        })

    if not targets:
        targets.append({
            "type": "Coverage",
            "name": sport or "Confirmed board",
            "sport": sport,
            "priority": 50,
            "reason": "No weak segment has enough history yet; add paper samples from the cleanest current board.",
        })

    unique: dict[tuple[str, str, str], dict] = {}
    for target in targets:
        key = (target.get("type", ""), target.get("name", ""), target.get("sport") or "")
        if key not in unique or int(target.get("priority", 0)) > int(unique[key].get("priority", 0)):
            unique[key] = target
    return sorted(unique.values(), key=lambda target: int(target.get("priority", 0)), reverse=True)[:8]


def _paper_calibration_suggestions(payload: AutoPaperCalibrationPayload, target: dict) -> list:
    sport = target.get("sport") or (None if payload.sport == "All Sports" else payload.sport.upper())
    raw_props: list[dict] = []
    source = "provider"
    if payload.prefer_confirmed:
        if sport is None:
            raw_props = _fetch_props(payload.platform, None)
            sport = _dominant_sport(raw_props)
        confirmed = _confirmed_props_payload(payload.platform, sport, limit=120)
        raw_props = confirmed.get("raw_props", [])
        source = "confirmed"
        if sport is None:
            sport = _sport_filter_from_text(confirmed.get("sport", "")) or _dominant_sport(raw_props)

    if not raw_props:
        raw_props = _fetch_props(payload.platform, sport)
        source = "provider"

    if sport is None:
        sport = _dominant_sport(raw_props)
    if sport is None and payload.sport == "All Sports":
        for candidate_sport in _available_prop_sports(raw_props):
            scoped_props = [prop for prop in raw_props if str(prop.get("league", "")).upper() == candidate_sport]
            suggestions = _paper_calibration_suggestions_for_props(payload, target, scoped_props, candidate_sport)
            if suggestions:
                for suggestion in suggestions:
                    suggestion.source = source
                return suggestions

    if not sport:
        return []

    suggestions = _paper_calibration_suggestions_for_props(payload, target, raw_props, sport)
    for suggestion in suggestions:
        suggestion.source = source
    return suggestions


def _paper_calibration_suggestions_for_props(payload: AutoPaperCalibrationPayload, target: dict, raw_props: list[dict], sport: str) -> list:
    if target.get("type") == "Stat":
        wanted = stat_type_from_text(target.get("name", "")).value
        raw_props = [
            prop for prop in raw_props
            if stat_type_from_text(prop.get("stat", "")).value == wanted
        ]
    elif target.get("type") == "Platform":
        raw_props = [
            prop for prop in raw_props
            if _canonical_platform(prop.get("platform", payload.platform)) == _canonical_platform(target.get("name", ""))
        ]

    suggestions = suggest_entries(
        raw_props,
        sport,
        _entry_platform_from_text(payload.platform),
        limit=5,
        leg_count=payload.leg_count,
        min_confidence=0,
        min_edge=-999,
        max_same_team=1,
        exclude_correlated=True,
        apply_feedback=True,
    )
    return suggestions


def _available_prop_sports(raw_props: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for prop in raw_props:
        sport = str(prop.get("league") or "").upper()
        if sport:
            counts[sport] = counts.get(sport, 0) + 1
    return [
        sport for sport, _count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        if sport in SUPPORTED_SPORTS
    ]


def _paper_calibration_audit(suggestion: dict, target: dict, backtest_data: dict, payload: AutoPaperCalibrationPayload) -> dict:
    return {
        "source": "auto_paper_calibration",
        "created_at": iso_utc(utc_now()),
        "entry_mode": "paper",
        "target": target,
        "request": payload.model_dump(),
        "scorecard": backtest_data.get("scorecard", {}),
        "recommendation": {
            "grade": suggestion.get("grade"),
            "action": suggestion.get("action"),
            "score": suggestion.get("score"),
            "leg_count": suggestion.get("leg_count"),
        },
        "note": "Auto-created as a zero-wager paper entry to improve calibration coverage. It has no bankroll impact.",
    }


def _entry_signature(entry: dict) -> tuple:
    return tuple(sorted(
        (
            str(prop.get("player", "")).strip().lower(),
            stat_type_from_text(prop.get("stat", "")).value,
            str(prop.get("direction", "Over")).strip().lower(),
            round(float(prop.get("line") or 0.0), 2),
            str(prop.get("game", "")).strip().lower(),
        )
        for prop in entry.get("props", [])
    ))


def _parlay_chat_suggestions(platform: str, request: dict, relaxed: bool = False) -> tuple[list, dict]:
    risk_profile = request.get("risk_profile") or "balanced"
    leg_count = int(request.get("leg_count") or 3)
    if risk_profile == "safe" and not relaxed:
        max_same_team = 1
        exclude_correlated = True
        min_confidence = 55
        min_edge = 0
    elif risk_profile == "aggressive" and not relaxed:
        max_same_team = 3
        exclude_correlated = False
        min_confidence = 0
        min_edge = -999
    else:
        max_same_team = 1 if not relaxed else 5
        exclude_correlated = not relaxed
        min_confidence = 0
        min_edge = -999

    source = "confirmed_props" if request.get("confirmed_only") and not relaxed else "provider_board"
    sport = request.get("sport")
    if source == "confirmed_props":
        payload = _confirmed_props_payload(platform, sport, limit=120)
        suggestion_sport = sport or _sport_filter_from_text(payload.get("sport", ""))
        if suggestion_sport:
            suggestions = suggest_entries(
                payload["raw_props"],
                suggestion_sport,
                _entry_platform_from_text(platform),
                limit=5,
                leg_count=leg_count,
                min_confidence=min_confidence,
                min_edge=min_edge,
                max_same_team=max_same_team,
                exclude_correlated=exclude_correlated,
                apply_feedback=True,
            )
        else:
            suggestions = []
        return suggestions, {
            "source": source,
            "relaxed": relaxed,
            "confirmed_count": payload.get("count", 0),
            "risk_profile": risk_profile,
            "max_same_team": max_same_team,
            "exclude_correlated": exclude_correlated,
            "min_confidence": min_confidence,
            "min_edge": min_edge,
        }

    suggestions = _optimized_entries(
        platform,
        sport,
        min_legs=leg_count,
        max_legs=leg_count,
        limit=5,
        min_confidence=min_confidence,
        min_edge=min_edge,
        max_same_team=max_same_team,
        exclude_correlated=exclude_correlated,
        apply_feedback=True,
    )
    return suggestions, {
        "source": source,
        "relaxed": relaxed,
        "risk_profile": risk_profile,
        "max_same_team": max_same_team,
        "exclude_correlated": exclude_correlated,
        "min_confidence": min_confidence,
        "min_edge": min_edge,
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
    return local_parlay_response(suggestions, request)[0]


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
    props = [prop for prop in normalize_props(rows, platform) if not is_combined_player_prop(prop)]
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
            "{\"platform\":\"PrizePicks|Underdog|Sleeper|Unknown\","
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
            "{\"platform\":\"PrizePicks|Underdog|Sleeper|Unknown\","
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


def _openai_parlay_response(message: str, suggestions: list[dict], request: dict | None = None) -> tuple[str | None, str | None]:
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
                    "include each leg's Over or Under direction, explain why it ranks first, respect the requested risk profile, "
                    "name the main watchout, and remind the user to bet responsibly."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"user_message": message, "request": request or {}, "candidates": suggestions[:5]},
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
    prefs = _user_preferences()
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
        "as_of": iso_utc(utc_now()),
        "cards": cards[:5],
        "avoid": avoid,
        "model_health": model,
        "preferences": prefs,
        "bankroll": {
            "current": dashboard_stats.get("bankroll", 0.0),
            "pending_exposure": dashboard_stats.get("pending_entry_exposure", 0.0),
            "recommendation_accuracy": dashboard_stats.get("recommendation_accuracy", {}),
        },
    }


def _new_daily_scan(platform: str, sport_filter: str | None, trigger: str = "manual") -> dict:
    started_at = iso_utc(utc_now())
    basis = f"{started_at}:{platform}:{sport_filter or 'All Sports'}:{trigger}"
    return {
        "id": hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12],
        "status": "scanning_props",
        "status_label": "Scanning Props",
        "message": "EdgeIQ is collecting provider lines and current board context.",
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "trigger": trigger,
        "started_at": started_at,
        "updated_at": started_at,
        "completed_at": "",
        "progress": 20,
        "steps": _daily_scan_steps("scanning_props"),
        "summary": {},
        "cache": {},
        "errors": [],
    }


def _daily_scan_steps(active: str) -> list[dict]:
    labels = [
        ("scanning_props", "Scanning Props"),
        ("analyzing_games", "Analyzing Games"),
        ("building_entries", "Building Entries"),
        ("ready", "Ready"),
    ]
    order = [key for key, _label in labels]
    active_index = order.index(active) if active in order else -1
    return [
        {
            "key": key,
            "label": label,
            "state": "complete" if index < active_index or active == "ready" else "active" if key == active else "pending",
        }
        for index, (key, label) in enumerate(labels)
    ]


def _save_daily_scan_status(scan: dict) -> dict:
    scan = {**scan, "updated_at": iso_utc(utc_now())}
    SettingsRepository.set(DAILY_SCAN_STATUS_KEY, json.dumps(scan))
    return scan


def _update_daily_scan(scan: dict, status: str, message: str, progress: int, **extra) -> dict:
    updated = {
        **scan,
        **extra,
        "status": status,
        "status_label": friendly_scan_status(status),
        "message": message,
        "progress": progress,
        "steps": _daily_scan_steps(status),
    }
    return _save_daily_scan_status(updated)


def friendly_scan_status(status: str) -> str:
    return {
        "not_run_today": "Not Run Today",
        "scanning_props": "Scanning Props",
        "analyzing_games": "Analyzing Games",
        "building_entries": "Building Entries",
        "ready": "Ready",
        "failed": "Failed",
    }.get(status, status.replace("_", " ").title())


def _run_daily_briefing_scan(
    platform: str,
    sport_filter: str | None,
    scan_id: str | None = None,
    trigger: str = "manual",
    sync_result: dict | None = None,
) -> dict:
    scan = _new_daily_scan(platform, sport_filter, trigger=trigger)
    if scan_id:
        scan["id"] = scan_id
    if sync_result:
        scan["sync_result"] = sync_result
    _save_daily_scan_status(scan)
    try:
        scan = _update_daily_scan(scan, "analyzing_games", "EdgeIQ is grouping games, checking injuries, and scoring the board.", 45)
        scan = _update_daily_scan(scan, "building_entries", "EdgeIQ is building Bet, Paper, Watch, and Avoid cards.", 70)
        briefing = _cached_daily_briefing_payload(platform, sport_filter, refresh=True)
        completed_at = iso_utc(utc_now())
        scan = _update_daily_scan(
            scan,
            "ready",
            "Today's briefing is ready.",
            100,
            completed_at=completed_at,
            summary=_daily_scan_summary(briefing),
            cache=briefing.get("cache", {}),
            errors=[],
        )
        _append_daily_scan_log(scan)
        return scan
    except Exception as exc:
        scan = _update_daily_scan(
            scan,
            "failed",
            "Daily briefing scan failed before the board was ready.",
            100,
            completed_at=iso_utc(utc_now()),
            errors=[str(exc)],
        )
        _append_daily_scan_log(scan)
        return scan


def _daily_scan_summary(briefing: dict) -> dict:
    sections = briefing.get("sections", {})
    return {
        "headline": briefing.get("headline", ""),
        "analyzed_props": int((briefing.get("summary") or {}).get("analyzed_props") or 0),
        "confirmed_props": int((briefing.get("summary") or {}).get("confirmed_props") or 0),
        "games": len(briefing.get("games_today") or []),
        "bet_cards": len(sections.get("bet") or []),
        "paper_cards": len(sections.get("paper") or []),
        "watch_cards": len(sections.get("watch") or []),
        "avoid_cards": len(sections.get("avoid") or []),
        "risk_level": (briefing.get("summary") or {}).get("risk_level", ""),
        "expected_value": (briefing.get("summary") or {}).get("expected_value", 0.0),
    }


def _append_daily_scan_log(scan: dict) -> None:
    raw = _safe_json_loads(SettingsRepository.get(DAILY_SCAN_LOG_KEY, ""))
    rows = raw.get("runs", []) if isinstance(raw, dict) else []
    rows = [scan, *[row for row in rows if row.get("id") != scan.get("id")]][:20]
    SettingsRepository.set(DAILY_SCAN_LOG_KEY, json.dumps({"runs": rows}))


def _daily_scan_status_payload(platform: str, sport_filter: str | None) -> dict:
    current = _safe_json_loads(SettingsRepository.get(DAILY_SCAN_STATUS_KEY, ""))
    log = _safe_json_loads(SettingsRepository.get(DAILY_SCAN_LOG_KEY, ""))
    runs = log.get("runs", []) if isinstance(log, dict) else []
    today = utc_now().date()
    if not current:
        current = {
            "id": "",
            "status": "not_run_today",
            "status_label": "Not Run Today",
            "message": "No Daily Briefing scan has run yet today.",
            "platform": platform,
            "sport": sport_filter or "All Sports",
            "started_at": "",
            "updated_at": "",
            "completed_at": "",
            "progress": 0,
            "steps": _daily_scan_steps(""),
            "summary": {},
            "cache": {},
            "errors": [],
        }
    elif current.get("completed_at"):
        try:
            completed = datetime.fromisoformat(str(current["completed_at"]).replace("Z", "+00:00"))
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
            if completed.date() != today:
                current = {
                    **current,
                    "status": "not_run_today",
                    "status_label": "Not Run Today",
                    "message": "No Daily Briefing scan has run yet today.",
                    "progress": 0,
                    "steps": _daily_scan_steps(""),
                }
        except ValueError:
            pass
    return {"current": current, "runs": runs[:8]}


def _cached_daily_briefing_payload(platform: str, sport_filter: str | None, refresh: bool = False, cached_only: bool = False) -> dict:
    key = _daily_briefing_cache_key(platform, sport_filter)
    if not refresh:
        cached = _safe_json_loads(SettingsRepository.get(key, ""))
        payload = cached.get("payload") if isinstance(cached, dict) and cached.get("version") == DAILY_BRIEFING_CACHE_VERSION else None
        if isinstance(payload, dict):
            fresh = _daily_briefing_cache_is_fresh(cached)
            return {
                **payload,
                "cache": {
                    "hit": True,
                    "key": key,
                    "created_at": cached.get("created_at", payload.get("as_of", "")),
                    "expires_at": cached.get("expires_at", ""),
                    "ttl_hours": DAILY_BRIEFING_CACHE_TTL_HOURS,
                    "stale": not fresh,
                    "requires_refresh": not fresh,
                    "refreshed": False,
                },
            }
        if cached_only:
            return _daily_briefing_placeholder(platform, sport_filter, key)

    payload = _daily_briefing_payload(platform, sport_filter)
    created_at = iso_utc(utc_now())
    expires_at = iso_utc(utc_now() + timedelta(hours=DAILY_BRIEFING_CACHE_TTL_HOURS))
    SettingsRepository.set(key, json.dumps({
        "created_at": created_at,
        "expires_at": expires_at,
        "version": DAILY_BRIEFING_CACHE_VERSION,
        "payload": payload,
    }))
    return {
        **payload,
        "cache": {
            "hit": False,
            "key": key,
            "created_at": created_at,
            "expires_at": expires_at,
            "ttl_hours": DAILY_BRIEFING_CACHE_TTL_HOURS,
            "stale": False,
            "requires_refresh": False,
            "refreshed": True,
        },
    }


def _daily_briefing_placeholder(platform: str, sport_filter: str | None, key: str) -> dict:
    dashboard_stats = get_dashboard()
    prefs = _user_preferences()
    monthly = dashboard_stats.get("monthly_profit", {})
    current_month = monthly.get("current_month", {})
    return {
        "as_of": iso_utc(utc_now()),
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "user": _daily_user_context(prefs),
        "headline": "No cached morning scan yet. Run Refresh to build today's board.",
        "summary": {
            "bankroll": dashboard_stats.get("bankroll", 0.0),
            "profit": dashboard_stats.get("profit", 0.0),
            "roi": dashboard_stats.get("roi", 0.0),
            "monthly_profit": current_month.get("profit", 0.0),
            "monthly_roi": current_month.get("roi", 0.0),
            "confirmed_props": 0,
            "excluded_props": 0,
            "analyzed_props": 0,
            "slate": [],
            "risk_level": "Scan Needed",
            "expected_value": 0.0,
            "model_health": _model_health_payload(),
        },
        "top_opportunities": [],
        "games_today": [],
        "provider_badges": _daily_provider_badges(platform, stale=True),
        "empty_states": {
            "bet": "Run Refresh to scan live provider lines before EdgeIQ shows a real-money card.",
            "paper": "Paper calibration cards appear after a scan identifies weak model segments.",
            "watch": "Watchlist alerts appear after timing, line movement, or injury checks are evaluated.",
            "avoid": "Avoid flags appear after EdgeIQ has enough current board data to reject props.",
        },
        "suggested_entries": [],
        "sections": {"bet": [], "paper": [], "watch": [], "avoid": []},
        "rules": [
            "Refresh runs the full provider scan before any real-money card is loaded.",
            "Cached briefings are labeled with their freshness status.",
            "Recheck injuries, game time, and line movement before placing.",
        ],
        "cache": {
            "hit": False,
            "key": key,
            "created_at": "",
            "expires_at": "",
            "ttl_hours": DAILY_BRIEFING_CACHE_TTL_HOURS,
            "stale": True,
            "requires_refresh": True,
            "cached_only": True,
            "refreshed": False,
        },
    }


def _daily_briefing_cache_is_fresh(cached: dict) -> bool:
    now = utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    expires_at = str(cached.get("expires_at") or "").strip()
    if expires_at:
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return expires > now
        except ValueError:
            return False

    created_at = str(cached.get("created_at") or "").strip()
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    if created.date() != now.date():
        return False
    return now - created < timedelta(hours=DAILY_BRIEFING_CACHE_TTL_HOURS)


def _daily_briefing_cache_key(platform: str, sport_filter: str | None) -> str:
    platform_key = "".join(ch.lower() if ch.isalnum() else "_" for ch in (platform or "PrizePicks")).strip("_") or "prizepicks"
    sport_key = "".join(ch.lower() if ch.isalnum() else "_" for ch in (sport_filter or "all_sports")).strip("_") or "all_sports"
    return f"daily_briefing_cache:{platform_key}:{sport_key}"


def _daily_user_context(prefs: dict) -> dict:
    name = str(prefs.get("display_name") or "Joshua").strip() or "Joshua"
    hour = datetime.now().hour
    greeting = "Good Morning" if hour < 12 else "Good Afternoon" if hour < 18 else "Good Evening"
    return {"display_name": name, "greeting": f"{greeting} {name}."}


def _daily_provider_badges(platform: str, stale: bool = False) -> list[dict]:
    canonical = _canonical_platform(platform)
    selected = _selected_entry_platforms(platform) if canonical == "Both" or canonical in ENTRY_PLATFORMS else [canonical]
    badges = []
    for name in selected:
        capability = _provider_capability(name)
        badges.append({
            "name": name,
            "role": capability["role"],
            "freshness": "Needs Refresh" if stale else "Fresh/Cache Checked",
            "status": "stale" if stale else "available",
            "entry_capable": capability["entry_capable"],
        })
    for name in CONTEXT_PLATFORMS:
        capability = _provider_capability(name)
        badges.append({
            "name": name,
            "role": capability["role"],
            "freshness": "Context Only",
            "status": "context",
            "entry_capable": False,
        })
    return badges


def _provider_capability(name: str) -> dict:
    canonical = _canonical_platform(name)
    if canonical in ENTRY_PLATFORMS:
        return {"role": "props + entries", "entry_capable": True}
    if canonical == "Ball Don't Lie":
        return {"role": "stats/context only", "entry_capable": False}
    return {"role": "context", "entry_capable": False}


def _daily_empty_states(
    bet_cards: list[dict],
    paper_cards: list[dict],
    watch_cards: list[dict],
    avoid_cards: list[dict],
    confirmed: dict,
) -> dict:
    analyzed = int(confirmed.get("analyzed_count", confirmed.get("count", 0) + confirmed.get("rejected_count", 0)) or 0)
    rejected = int(confirmed.get("rejected_count") or 0)
    return {
        "bet": "No real-money card cleared trust, timing, and data-quality thresholds." if not bet_cards else "",
        "paper": "No paper entry is needed; calibration coverage is acceptable for this filter." if not paper_cards else "",
        "watch": "No watch items need a final injury, timing, or line check." if not watch_cards else "",
        "avoid": f"No avoid flags after analyzing {analyzed} props and filtering {rejected} weak rows." if not avoid_cards else "",
    }


def _daily_briefing_payload(platform: str, sport_filter: str | None) -> dict:
    dashboard_stats = get_dashboard()
    prefs = _user_preferences()
    command = _command_center_payload(platform, sport_filter)
    confirmed = _confirmed_props_payload(platform, sport_filter, limit=80)
    bet_cards = _daily_bet_cards(command["cards"])
    paper_cards = _daily_paper_cards(platform, sport_filter, dashboard_stats)
    watch_cards = _daily_watch_cards(platform, sport_filter, command, confirmed)
    avoid_cards = _daily_avoid_cards(command, confirmed)
    monthly = dashboard_stats.get("monthly_profit", {})
    current_month = monthly.get("current_month", {})
    top_opportunities = _daily_top_opportunities(command, confirmed)
    risk_summary = _daily_risk_summary(bet_cards, watch_cards, paper_cards)
    games_today = _daily_games_today(platform, sport_filter, confirmed)
    return {
        "as_of": iso_utc(utc_now()),
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "user": _daily_user_context(prefs),
        "headline": _daily_briefing_headline(bet_cards, paper_cards, watch_cards, avoid_cards),
        "summary": {
            "bankroll": dashboard_stats.get("bankroll", 0.0),
            "profit": dashboard_stats.get("profit", 0.0),
            "roi": dashboard_stats.get("roi", 0.0),
            "monthly_profit": current_month.get("profit", 0.0),
            "monthly_roi": current_month.get("roi", 0.0),
            "confirmed_props": confirmed.get("count", 0),
            "excluded_props": confirmed.get("rejected_count", 0),
            "analyzed_props": confirmed.get("analyzed_count", confirmed.get("count", 0) + confirmed.get("rejected_count", 0)),
            "slate": confirmed.get("slate", []),
            "risk_level": risk_summary["risk_level"],
            "expected_value": risk_summary["expected_value"],
            "model_health": command.get("model_health", {}),
        },
        "top_opportunities": top_opportunities,
        "games_today": games_today,
        "provider_badges": _daily_provider_badges(platform),
        "empty_states": _daily_empty_states(bet_cards, paper_cards, watch_cards, avoid_cards, confirmed),
        "suggested_entries": _daily_suggested_entries(bet_cards, watch_cards, paper_cards),
        "sections": {
            "bet": bet_cards,
            "paper": paper_cards,
            "watch": watch_cards,
            "avoid": avoid_cards,
        },
        "rules": [
            "Real-money cards are loaded into the entry builder and still require user confirmation.",
            "Paper cards are zero-wager calibration candidates.",
            "Recheck injuries, game time, and line movement before placing.",
        ],
    }


def _daily_bet_cards(cards: list[dict]) -> list[dict]:
    entry_cards = [card for card in cards if card.get("type") == "entry"]
    release_ready = [
        card for card in entry_cards
        if (
            float((card.get("trust") or {}).get("score") or 0) >= 64
            and (card.get("trust") or {}).get("label") != "Paper First"
        )
    ]
    if not release_ready and entry_cards:
        best_card = max(entry_cards, key=lambda card: (float((card.get("trust") or {}).get("score") or 0), float(card.get("score") or 0)))
        fallback = dict(best_card)
        fallback["title"] = "Daily Best Card"
        fallback["summary"] = "Best-qualified real-money card from today's scan."
        fallback["warnings"] = [
            *fallback.get("warnings", []),
            "This is the strongest available card, but it did not meet the stricter release-ready threshold.",
        ]
        release_ready = [fallback]
    return [
        _daily_action_card("bet", card, "Load Slip", _bet_card_reason(card))
        for card in release_ready[:3]
    ]


def _daily_top_opportunities(command: dict, confirmed: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str, float]] = set()
    sources = []
    for card in command.get("cards", []):
        sources.extend(card.get("props", []))
    sources.extend(confirmed.get("props", []))
    for prop in sources:
        player = str(prop.get("player", "")).strip()
        stat = str(prop.get("stat", "")).strip()
        direction = str(prop.get("direction") or "Over").strip()
        line = float(prop.get("line") or 0.0)
        if not player or not stat or not line:
            continue
        key = (player.lower(), stat.lower(), direction.lower(), round(line, 2))
        if key in seen:
            continue
        seen.add(key)
        confidence = float(prop.get("confidence") or prop.get("confirmed_score") or 0.0)
        quality = float((prop.get("data_quality") or {}).get("score") or 50.0)
        score = max(confidence, (confidence * 0.74) + (quality * 0.18) + min(8.0, abs(float(prop.get("edge") or 0.0)) * 3.0))
        rows.append({
            "player": player,
            "stat": stat,
            "direction": direction,
            "line": line,
            "sport": prop.get("sport") or prop.get("league") or "",
            "platform": prop.get("platform", ""),
            "confidence": round(confidence, 1),
            "score": round(max(0.0, min(100.0, score)), 1),
            "stars": _opportunity_stars(score),
        })
    rows.sort(key=lambda row: (row["score"], row["confidence"]), reverse=True)
    return rows[:5]


def _daily_games_today(platform: str, sport_filter: str | None, confirmed: dict) -> list[dict]:
    props = confirmed.get("props") or []
    if not props:
        props = [_analyzed_feed_prop(prop) for prop in _fetch_props(platform, sport_filter)[:80]]
    groups: dict[tuple[str, str], list[dict]] = {}
    for prop in props:
        game = str(prop.get("game") or "").strip()
        if not game:
            continue
        sport = str(prop.get("sport") or prop.get("league") or sport_filter or "All Sports").upper()
        groups.setdefault((sport, game), []).append(prop)

    games = []
    for (sport, game), game_props in groups.items():
        if len(games) >= 8:
            break
        games.append(_daily_game_card(platform, sport, game, game_props))
    games.sort(key=lambda game: (game["ai_score"], game["prop_count"]), reverse=True)
    return games[:6]


def _daily_game_card(platform: str, sport: str, game: str, props: list[dict]) -> dict:
    ranked = sorted(props, key=lambda prop: (float(prop.get("confidence") or prop.get("confirmed_score") or 0), float(prop.get("edge") or 0), int(prop.get("trending_count") or 0)), reverse=True)
    best_prop = ranked[0] if ranked else {}
    value_prop = max(ranked, key=lambda prop: abs(float(prop.get("edge") or 0)), default=best_prop)
    high_confidence = max(ranked, key=lambda prop: float(prop.get("confidence") or 0), default=best_prop)
    fade = min(ranked, key=lambda prop: (float(prop.get("confidence") or 0), float(prop.get("edge") or 0)), default={})
    avg_confidence = sum(float(prop.get("confidence") or 0) for prop in ranked) / len(ranked) if ranked else 0.0
    avg_edge = sum(float(prop.get("edge") or 0) for prop in ranked) / len(ranked) if ranked else 0.0
    teams = _teams_from_game(game, ranked)
    matchup_label = _matchup_label(game, teams)
    movement = best_prop.get("line_movement") or {}
    try:
        weather_signal = openweather.weather_signal(openweather.fetch_weather_for_game(game, sport)) if sport in {"NFL", "MLB"} else None
    except Exception:
        weather_signal = None
    return {
        "game": game,
        "matchup_label": matchup_label,
        "sport": sport,
        "platform": platform,
        "teams": teams,
        "prop_count": len(ranked),
        "projected_winner": _projected_winner(teams, ranked),
        "team_pace": _team_pace_label(ranked),
        "injuries": _game_injury_summary(ranked),
        "best_prop": _daily_game_prop(best_prop),
        "best_value_prop": _daily_game_prop(value_prop),
        "highest_confidence": _daily_game_prop(high_confidence),
        "fade_candidate": _daily_game_prop(fade),
        "vegas_line": _vegas_line_proxy(best_prop),
        "ai_score": round(max(0.0, min(100.0, (avg_confidence * 0.72) + (abs(avg_edge) * 6.0) + min(12.0, len(ranked) * 1.5))), 1),
        "probability": round(max(0.0, min(100.0, avg_confidence)), 1),
        "line_movement": movement.get("label") or movement.get("direction") or "flat",
        "public_betting": _public_betting_proxy(best_prop),
        "weather": weather_signal.get("message") if weather_signal else ("Indoor/no weather edge" if sport not in {"NFL", "MLB"} else "No weather flag"),
        "generated_entry": {
            "props": [_daily_game_prop(prop) for prop in ranked[:2]],
            "label": "Generate Entry",
        },
    }


def _daily_game_prop(prop: dict) -> dict:
    if not prop:
        return {}
    return {
        "player": prop.get("player", ""),
        "team": prop.get("team", ""),
        "sport": prop.get("sport") or prop.get("league") or "",
        "stat": prop.get("stat", ""),
        "direction": prop.get("direction", "Over"),
        "line": prop.get("line"),
        "projection": prop.get("projection"),
        "confidence": prop.get("confidence", 0),
        "edge": prop.get("edge", 0),
        "platform": prop.get("platform", ""),
        "game": prop.get("game", ""),
        "game_time": prop.get("game_time", ""),
        "trending_count": prop.get("trending_count", 0),
    }


def _teams_from_game(game: str, props: list[dict] | None = None) -> list[str]:
    for separator in (" vs ", " @ ", "-", "·"):
        if separator in game:
            return [part.strip() for part in game.split(separator, 1) if part.strip()]
    prop_teams = []
    for prop in props or []:
        team = str(prop.get("team") or "").strip()
        if team and team not in prop_teams:
            prop_teams.append(team)
    if prop_teams:
        if game and game not in prop_teams:
            return [prop_teams[0], game]
        if len(prop_teams) >= 2:
            return prop_teams[:2]
    return [game] if game else []


def _matchup_label(game: str, teams: list[str]) -> str:
    if len(teams) >= 2:
        return f"{teams[0]} vs {teams[1]}"
    return game or (teams[0] if teams else "Matchup TBD")


def _projected_winner(teams: list[str], props: list[dict]) -> str:
    if len(teams) < 2:
        return teams[0] if teams else "Lean unavailable"
    team_scores = {team: 0.0 for team in teams}
    for prop in props:
        team = str(prop.get("team") or "").strip()
        if team in team_scores:
            team_scores[team] += float(prop.get("confidence") or 0) + max(0.0, float(prop.get("edge") or 0) * 4.0)
    winner, score = max(team_scores.items(), key=lambda item: item[1])
    return winner if score > 0 else teams[0]


def _team_pace_label(props: list[dict]) -> str:
    avg_trending = sum(int(prop.get("trending_count") or 0) for prop in props) / len(props) if props else 0
    if avg_trending >= 5000:
        return "Fast / high market activity"
    if avg_trending >= 1000:
        return "Medium"
    return "Slow / selective"


def _game_injury_summary(props: list[dict]) -> str:
    risky = []
    for prop in props[:5]:
        try:
            availability = _player_availability_payload(prop.get("player", ""), prop.get("sport", ""), prop.get("team", ""), prop.get("game", ""))
        except Exception:
            continue
        if float(availability.get("availability_score") or 100) < 70:
            risky.append(f"{availability.get('player')} {availability.get('status')}")
    return ", ".join(risky[:2]) if risky else "No major matched injury flag"


def _vegas_line_proxy(prop: dict) -> str:
    if not prop:
        return "Unavailable"
    return f"{prop.get('platform', 'Market')} {prop.get('direction', 'Over')} {prop.get('line', '-')}"


def _public_betting_proxy(prop: dict) -> str:
    trending = int(prop.get("trending_count") or 0) if prop else 0
    public = max(50, min(78, 50 + trending // 900))
    return f"{public}% on visible market interest"


def _opportunity_stars(score: float) -> str:
    filled = 5 if score >= 84 else 4 if score >= 74 else 3 if score >= 64 else 2 if score >= 54 else 1
    return "★" * filled + "☆" * (5 - filled)


def _daily_risk_summary(bet_cards: list[dict], watch_cards: list[dict], paper_cards: list[dict]) -> dict:
    cards = bet_cards or watch_cards or paper_cards
    if not cards:
        return {"risk_level": "No Card", "expected_value": 0.0}
    trust_scores = [_daily_card_trust_score(card) for card in cards]
    leg_counts = [
        len(card.get("props") or [])
        for card in cards
        if card.get("props")
    ]
    avg_trust = sum(trust_scores) / len(trust_scores) if trust_scores else 0.0
    max_legs = max(leg_counts, default=1)
    if not bet_cards:
        risk = "Medium" if watch_cards else "Paper First"
    elif avg_trust >= 72 and max_legs <= 3:
        risk = "Low"
    elif avg_trust >= 55 and max_legs <= 4:
        risk = "Medium"
    else:
        risk = "High"
    expected_value = round(max(-8.0, min(11.0 if not bet_cards else 18.0, (avg_trust - 50.0) * 0.45)), 1)
    return {"risk_level": risk, "expected_value": expected_value}


def _daily_card_trust_score(card: dict) -> float:
    trust = card.get("trust") or {}
    if trust.get("score") is not None:
        return float(trust.get("score") or 0.0)
    props = card.get("props") or []
    confidences = [float(prop.get("confidence") or 0.0) for prop in props if prop.get("confidence") is not None]
    if confidences:
        return sum(confidences) / len(confidences)
    return min(64.0, float(card.get("score") or 0.0))


def _daily_suggested_entries(bet_cards: list[dict], watch_cards: list[dict], paper_cards: list[dict]) -> list[dict]:
    source_cards = bet_cards or watch_cards or paper_cards
    available = sorted({
        len(card.get("props") or [])
        for card in source_cards
        if len(card.get("props") or []) >= 2
    })
    defaults = [2, 3, 5]
    entries = []
    for legs in defaults:
        entries.append({
            "label": f"{legs}-Leg",
            "legs": legs,
            "available": legs in available or bool(source_cards),
            "prompt": f"Give me the best confirmed {legs}-leg entry",
        })
    return entries


def _daily_paper_cards(platform: str, sport_filter: str | None, dashboard_stats: dict) -> list[dict]:
    backtest_data = backtest_summary(BetRepository().get_all(), EntryRepository.all())
    selected_sport = sport_filter or "All Sports"
    payload = AutoPaperCalibrationPayload(
        platform=platform,
        sport=selected_sport,
        leg_count=2,
        max_entries=2,
        prefer_confirmed=False,
        dry_run=True,
    )
    cards: list[dict] = []
    signatures: set[tuple] = set()
    for target in _calibration_learning_targets(backtest_data, selected_sport):
        for suggestion in _paper_calibration_suggestions(payload, target):
            serialized = _serialize_suggestion(suggestion)
            signature = _entry_signature(serialized["entry"])
            if signature in signatures:
                continue
            signatures.add(signature)
            card = _command_suggestion_card(
                "Paper Calibration",
                target.get("reason", "Paper-only sample to strengthen model calibration."),
                suggestion,
            )
            action = _daily_action_card("paper", card, "Load Paper", target.get("reason", "Paper-only sample to improve calibration."))
            action["calibration_target"] = target
            action["entry_mode"] = "paper"
            cards.append(action)
            if len(cards) >= 2:
                return cards
    paper = (dashboard_stats.get("entries") or {}).get("paper", {})
    if not cards and int(paper.get("pending") or 0):
        cards.append({
            "type": "paper_status",
            "title": "Paper Calibration Active",
            "summary": f"{paper.get('pending', 0)} paper entries are already pending.",
            "reason": "Let the pending calibration samples settle before creating more.",
            "props": [],
            "stake": {"amount": 0.0, "unit_label": "Paper only"},
            "trust": {"score": 0, "label": "Learning"},
            "timing": {"score": 0, "label": "Pending"},
            "button_label": "View Performance",
        })
    return cards


def _daily_watch_cards(platform: str, sport_filter: str | None, command: dict, confirmed: dict) -> list[dict]:
    watches: list[dict] = []
    for alert in _market_timing_alert_rows(platform, sport_filter, 4, -110, min_confidence=0, min_ev=-25, alert_type="All", hide_outliers=True):
        if alert.get("type") in {"Avoid", "Line Moved Against Price"}:
            continue
        watches.append({
            "type": "watch",
            "title": alert.get("type", "Watch"),
            "summary": alert.get("action", "Monitor before placing."),
            "reason": alert.get("reason", "Timing signal needs another check before placing."),
            "props": [{
                "player": alert.get("player", ""),
                "stat": alert.get("stat", ""),
                "direction": alert.get("direction", "Over"),
                "line": alert.get("line"),
                "platform": alert.get("platform", ""),
                "sport": alert.get("sport", ""),
                "game": alert.get("game", ""),
                "game_time": alert.get("game_time", ""),
                "confidence": alert.get("confidence", 0),
                "edge": alert.get("edge", 0),
                "projection": alert.get("projection"),
            }],
            "score": alert.get("priority_score", 0),
            "button_label": "Load Prop",
        })
        if len(watches) >= 3:
            return watches
    for card in command.get("cards", []):
        trust = float((card.get("trust") or {}).get("score") or 0)
        if 45 <= trust < 58:
            watches.append(_daily_action_card("watch", card, "Load to Review", "Interesting, but trust is below the real-money threshold."))
        if len(watches) >= 3:
            break
    if not watches and confirmed.get("count", 0):
        watches.append({
            "type": "watch_status",
            "title": "Confirmed Board Ready",
            "summary": f"{confirmed.get('count', 0)} confirmed props are available.",
            "reason": "No urgent watch alert fired, but the board has enough clean props to review.",
            "props": (confirmed.get("props") or [])[:2],
            "button_label": "Open Confirmed Props",
        })
    return watches


def _daily_avoid_cards(command: dict, confirmed: dict) -> list[dict]:
    avoids = []
    for prop in (command.get("avoid") or [])[:3]:
        avoids.append({
            "type": "avoid",
            "title": "Pass For Now",
            "summary": f"{prop.get('player', 'Prop')} {prop.get('direction', 'Over')} {prop.get('stat', '')}",
            "reason": _avoid_reason(prop),
            "props": [prop],
            "button_label": "Review",
        })
    if confirmed.get("rejected_count", 0):
        avoids.append({
            "type": "avoid_status",
            "title": "Filtered Board",
            "summary": f"{confirmed.get('rejected_count', 0)} props excluded by validation.",
            "reason": "EdgeIQ hid props missing game time, line sanity, player identity, or daily-market confirmation.",
            "props": [],
            "button_label": "View Confirmed Board",
        })
    return avoids[:4]


def _daily_action_card(section: str, card: dict, button_label: str, reason: str) -> dict:
    explanation = card.get("explanation")
    if explanation:
        explanation = {
            **explanation,
            "evidence": _daily_card_evidence(section, card, reason),
            "freshness": _daily_card_freshness(card),
        }
    return {
        "type": section,
        "title": card.get("title", "Recommendation"),
        "summary": card.get("summary", ""),
        "reason": reason,
        "score": card.get("score", 0),
        "grade": card.get("grade", "-"),
        "action": card.get("action", ""),
        "props": card.get("props", []),
        "suggestion": card.get("suggestion"),
        "warnings": card.get("warnings", []),
        "trust": card.get("trust", {}),
        "timing": card.get("timing", {}),
        "stake": card.get("stake", {}),
        "explanation": explanation,
        "button_label": button_label,
    }


def _daily_card_evidence(section: str, card: dict, reason: str) -> list[str]:
    props = card.get("props") or []
    quality_scores = [
        float((prop.get("data_quality") or {}).get("score") or 0)
        for prop in props
        if prop.get("data_quality")
    ]
    evidence = [reason]
    if props:
        evidence.append(f"{len(props)} leg{'s' if len(props) != 1 else ''} reviewed with average confidence {sum(float(prop.get('confidence') or 0) for prop in props) / len(props):.1f}%.")
    if quality_scores:
        evidence.append(f"Average data-quality score {sum(quality_scores) / len(quality_scores):.1f}/100.")
    platforms = sorted({str(prop.get("platform") or "").strip() for prop in props if prop.get("platform")})
    if platforms:
        evidence.append(f"Entry-capable provider context: {', '.join(platforms)}.")
    if section == "bet":
        evidence.append("Still requires user confirmation before any real-money placement.")
    elif section == "paper":
        evidence.append("Paper-only calibration card with zero bankroll impact.")
    elif section == "watch":
        evidence.append("Watch item needs one more freshness, timing, or injury check.")
    elif section == "avoid":
        evidence.append("Avoid item is excluded from real-money entry generation.")
    return evidence


def _daily_card_freshness(card: dict) -> dict:
    props = card.get("props") or []
    stale = any((prop.get("data_quality") or {}).get("label") == "Thin" for prop in props)
    return {
        "label": "Needs Review" if stale else "Fresh/Cache Checked",
        "status": "warning" if stale else "available",
    }


def _bet_card_reason(card: dict) -> str:
    trust = card.get("trust") or {}
    timing = card.get("timing") or {}
    stake = card.get("stake") or {}
    return (
        f"{trust.get('label', 'Playable')} trust at {float(trust.get('score') or 0):.0f}, "
        f"{timing.get('label', 'Monitor').lower()} timing, suggested stake {float(stake.get('amount') or 0):.2f}."
    )


def _avoid_reason(prop: dict) -> str:
    confidence = float(prop.get("confidence") or 0)
    edge = float(prop.get("edge") or 0)
    if confidence < 50 and edge < 0:
        return "Low confidence and negative projected edge."
    if confidence < 50:
        return "Confidence is below the morning-card threshold."
    if edge < 0:
        return "Projected edge is negative at the current line."
    return "Flagged for review by the command-center guardrails."


def _daily_briefing_headline(bet_cards: list[dict], paper_cards: list[dict], watch_cards: list[dict], avoid_cards: list[dict]) -> str:
    if bet_cards:
        return f"{len(bet_cards)} playable slip{'s' if len(bet_cards) != 1 else ''} found for today's card."
    if paper_cards:
        return "No real-money card cleared; EdgeIQ found paper calibration work."
    if watch_cards:
        return "No immediate bet; monitor the watchlist before placing."
    if avoid_cards:
        return "Today's board is mostly a pass until lines or data improve."
    return "No morning card is available for the current filters yet."


def _command_single_card(prop: dict) -> dict:
    trust = _trust_score_for_props([prop], [])
    timing = _market_timing_score_for_props([prop])
    line_shop_summary = _line_shop_summary_for_props([prop])
    stake = _stake_recommendation_for_props([prop], trust)
    return {
        "type": "single",
        "title": "Best Single",
        "summary": "Highest-confidence prop on the current board.",
        "score": round((prop["confidence"] * 0.78) + (prop["edge"] * 7) + min(8, prop["trending_count"] / 20000), 1),
        "grade": _grade_from_confidence(prop["confidence"]),
        "action": f"{prop['direction']} {prop['stat']}",
        "props": [prop],
        "warnings": [],
        "trust": trust,
        "timing": timing,
        "line_shop": line_shop_summary,
        "stake": stake,
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
    props = serialized["entry"]["props"]
    warnings = serialized["warnings"]
    trust = _trust_score_for_props(props, warnings)
    timing = _market_timing_score_for_props(props)
    line_shop_summary = _line_shop_summary_for_props(props)
    stake = _stake_recommendation_for_props(props, trust)
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
        "props": props,
        "warnings": warnings,
        "trust": trust,
        "timing": timing,
        "line_shop": line_shop_summary,
        "stake": stake,
        "explanation": _recommendation_explanation(
            title=title,
            score=serialized["score"],
            grade=serialized["grade"],
            props=props,
            warnings=warnings,
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
    trust = _trust_score_for_props(props, warnings)
    timing = _market_timing_score_for_props(props)
    return {
        "title": title,
        "summary": summary,
        "grade": grade,
        "score": score,
        "trust": trust,
        "timing": timing,
        "average_confidence": round(avg_confidence, 1),
        "average_edge": round(avg_edge, 2),
        "source_count": len(sources),
        "sources": sources,
        "signals": signals,
        "warnings": warnings,
        "why": _why_this_recommendation(props, avg_confidence, avg_edge, sources),
        "breakers": _recommendation_breakers(props, warnings),
        "no_bet_rule": _no_bet_rule(props, trust),
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


def _why_this_recommendation(props: list[dict], avg_confidence: float, avg_edge: float, sources: list[str]) -> str:
    if not props:
        return "No legs were supplied for this recommendation."
    source_text = f" with support from {', '.join(sources[:3])}" if sources else ""
    return (
        f"EdgeIQ likes the blend of {avg_confidence:.1f}% confidence, "
        f"{avg_edge:+.2f} average edge, and current market interest{source_text}."
    )


def _recommendation_breakers(props: list[dict], warnings: list[str]) -> list[str]:
    breakers = list(warnings[:3])
    if any(float((prop.get("data_quality") or {}).get("score") or 100) < 60 for prop in props):
        breakers.append("Some legs have thin source or history coverage.")
    if any(abs(float((prop.get("line_movement") or {}).get("change") or 0)) >= 2 for prop in props):
        breakers.append("A large line move may mean the best price is already gone.")
    if any(float(prop.get("confidence") or 0) < 52 for prop in props):
        breakers.append("At least one leg is near the confidence floor.")
    return breakers[:4] or ["Main risk is normal variance; no major model breaker was detected."]


def _no_bet_rule(props: list[dict], trust: dict) -> str:
    low_confidence = min((float(prop.get("confidence") or 0) for prop in props), default=0.0)
    if trust.get("score", 0) < 50:
        return "No-bet unless new data raises trust above 50 or this is paper-only."
    if low_confidence < 50:
        return "No-bet if the weak leg cannot be swapped above 50% confidence."
    return "Playable while the posted line remains within 0.5 of the analyzed number."


def _trust_score_for_props(props: list[dict], warnings: list[str] | None = None) -> dict:
    warnings = warnings or []
    if not props:
        return {"score": 0.0, "label": "No Data", "components": {}, "flags": ["No props supplied."]}
    avg_confidence = sum(float(prop.get("confidence") or 0) for prop in props) / len(props)
    avg_edge = sum(float(prop.get("edge") or 0) for prop in props) / len(props)
    quality_scores = [float((prop.get("data_quality") or {}).get("score") or 50.0) for prop in props]
    avg_quality = sum(quality_scores) / len(quality_scores)
    source_count = len({
        signal.get("source", "")
        for prop in props
        for signal in prop.get("source_signals", [])
        if signal.get("source")
    })
    line_edges = [_best_line_edge_for_prop(prop) for prop in props]
    line_score = 50.0 + min(25.0, sum(line_edges) * 4.0)
    correlation_penalty = min(18.0, len(warnings) * 6.0)
    edge_score = max(0.0, min(100.0, 52.0 + avg_edge * 8.0))
    source_score = min(100.0, 45.0 + source_count * 10.0)
    score = round(
        (avg_confidence * 0.28)
        + (edge_score * 0.22)
        + (avg_quality * 0.2)
        + (source_score * 0.14)
        + (line_score * 0.16)
        - correlation_penalty,
        1,
    )
    score = max(0.0, min(100.0, score))
    label = "Release Ready" if score >= 78 else "Playable" if score >= 64 else "Paper First" if score >= 50 else "Pass"
    flags = []
    if avg_quality < 60:
        flags.append("Data depth is still thin.")
    if not source_count:
        flags.append("Few external source confirmations.")
    if warnings:
        flags.append("Correlation or context warnings present.")
    if sum(line_edges) <= 0:
        flags.append("No obvious line-shopping advantage.")
    return {
        "score": score,
        "label": label,
        "components": {
            "confidence": round(avg_confidence, 1),
            "edge": round(edge_score, 1),
            "data_quality": round(avg_quality, 1),
            "source_agreement": round(source_score, 1),
            "line_value": round(max(0.0, min(100.0, line_score)), 1),
            "correlation_penalty": round(correlation_penalty, 1),
        },
        "flags": flags[:4],
    }


def _best_line_edge_for_prop(prop: dict) -> float:
    player = prop.get("player", "")
    stat = prop.get("stat", "")
    sport = prop.get("sport") or prop.get("league") or None
    direction = prop.get("direction") or "Over"
    current_line = float(prop.get("line") or 0.0)
    if not player or not stat or not current_line:
        return 0.0
    try:
        matches = _matching_market_props(player, stat, sport, "Both")
    except Exception:
        return 0.0
    game = str(prop.get("game", "")).strip().upper()
    if game:
        same_game = [row for row in matches if str(row.get("game", "")).strip().upper() == game]
        if same_game:
            matches = same_game
    if not matches:
        return 0.0
    best_row = min(matches, key=lambda row: float(row.get("line") or current_line)) if direction == "Over" else max(matches, key=lambda row: float(row.get("line") or current_line))
    best_line = float(best_row.get("line") or current_line)
    return round(current_line - best_line, 2) if direction == "Over" else round(best_line - current_line, 2)


def _market_timing_score_for_props(props: list[dict]) -> dict:
    scores = []
    notes = []
    for prop in props:
        movement = prop.get("line_movement") or {}
        change = float(movement.get("change") or 0.0)
        direction = prop.get("direction") or "Over"
        supports = _market_move_supports_pick(direction, change)
        better = _line_move_improves_price(direction, change)
        score = 50.0
        score += min(18.0, abs(change) * 5.0) if supports else 0.0
        score += 12.0 if better else 0.0
        score += 10.0 if abs(float(prop.get("edge") or 0.0)) >= 1.0 else 0.0
        score += 8.0 if float(prop.get("confidence") or 0.0) >= 60 else 0.0
        if _is_outlier_line_move(float(prop.get("line") or 0.0), abs(change)):
            score -= 22.0
            notes.append(f"{prop.get('player', 'A leg')} has an unusually large move; verify news.")
        elif better:
            notes.append(f"{prop.get('player', 'A leg')} is at a better number now.")
        elif supports:
            notes.append(f"{prop.get('player', 'A leg')} has market support.")
        scores.append(max(0.0, min(100.0, score)))
    avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    return {
        "score": avg,
        "label": "Bet Now" if avg >= 74 else "Good Window" if avg >= 62 else "Monitor" if avg >= 50 else "Wait",
        "notes": notes[:4] or ["No urgent timing signal yet."],
    }


def _stake_recommendation_for_props(props: list[dict], trust: dict) -> dict:
    strategy = _bankroll_strategy()
    dashboard_stats = get_dashboard()
    bankroll = max(0.0, float(dashboard_stats.get("bankroll") or 0.0))
    if strategy["mode"] == "paper":
        return {"mode": "paper", "amount": 0.0, "unit_label": "Paper only", "reason": "Strategy is set to paper calibration."}
    if not bankroll:
        return {"mode": strategy["mode"], "amount": 0.0, "unit_label": "No bankroll", "reason": "Set bankroll to unlock stake sizing."}
    trust_score = float(trust.get("score") or 0.0)
    risk_multiplier = 0.45 if len(props) >= 4 else 0.65 if len(props) == 3 else 0.85
    if strategy["mode"] == "flat":
        amount = float(strategy["unit_size"])
    elif strategy["mode"] == "conservative":
        amount = min(float(strategy["unit_size"]), bankroll * 0.01) * risk_multiplier
    elif strategy["mode"] == "aggressive":
        amount = min(bankroll * float(strategy["max_wager_pct"]) / 100, float(strategy["unit_size"]) * 2.0) * (0.75 + trust_score / 200)
    elif strategy["mode"] == "kelly":
        avg_probability = sum(float(prop.get("hit_rate", {}).get("estimated_hit_rate") or prop.get("confidence") or 50) for prop in props) / len(props)
        amount = suggested_wager(-110, avg_probability / 100, bankroll) * risk_multiplier
    else:
        amount = float(strategy["unit_size"]) * risk_multiplier * (0.75 + trust_score / 200)
    cap = bankroll * float(strategy["max_wager_pct"]) / 100
    amount = round(max(0.0, min(amount, cap)), 2)
    return {
        "mode": strategy["mode"],
        "amount": amount,
        "unit_label": f"{strategy['mode'].title()} sizing",
        "reason": f"Capped at {strategy['max_wager_pct']:.1f}% bankroll with {trust.get('label', 'trust')} trust.",
    }


def _line_shop_summary_for_props(props: list[dict]) -> dict:
    rows = []
    for prop in props:
        edge = _best_line_edge_for_prop(prop)
        rows.append({
            "player": prop.get("player", ""),
            "stat": prop.get("stat", ""),
            "direction": prop.get("direction", "Over"),
            "platform": prop.get("platform", ""),
            "line": prop.get("line"),
            "best_line_edge": edge,
        })
    positives = [row for row in rows if row["best_line_edge"] > 0]
    return {
        "checked": len(rows),
        "positive_edges": len(positives),
        "best_edge": max((row["best_line_edge"] for row in rows), default=0.0),
        "legs": rows,
        "message": "Best-line value found." if positives else "No better matching line found yet.",
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


def _advantage_center_payload(platform: str, sport_filter: str | None) -> dict:
    command = _command_center_payload(platform, sport_filter)
    clv = clv_report()
    timing = _market_timing_alert_rows(platform, sport_filter, 5, -110, min_confidence=0, min_ev=-25, alert_type="All", hide_outliers=True)
    profile = _personal_profile_payload()
    watch = _watchlist_alerts()
    top_card = command["cards"][0] if command["cards"] else None
    return {
        "as_of": iso_utc(utc_now()),
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "top_recommendation": top_card,
        "trust_score": top_card.get("trust") if top_card else {"score": 0, "label": "No board"},
        "best_line_finder": _line_shop_summary_for_props(top_card.get("props", [])) if top_card else {"checked": 0, "legs": []},
        "closing_line_value": {
            "average_clv": clv.get("average_clv", 0.0),
            "positive_clv_rate": clv.get("positive_clv_rate", 0.0),
            "tracked_legs": clv.get("tracked_legs", 0),
        },
        "personal_profile": profile,
        "watchlist_alerts": watch[:5],
        "timing_alerts": timing,
        "bankroll_strategy": _bankroll_strategy(),
        "game_contexts": _advantage_game_contexts(platform, sport_filter),
        "competitive_features": [
            {"name": "Best Line Finder", "status": "active"},
            {"name": "Closing Line Value", "status": "active"},
            {"name": "Personal Model Profile", "status": "active"},
            {"name": "Prop Watchlist", "status": "active"},
            {"name": "Live Edge Decay", "status": "active"},
            {"name": "Explainable Cards", "status": "active"},
            {"name": "Game Environment", "status": "active"},
            {"name": "Bankroll Modes", "status": "active"},
            {"name": "Promo Boost Analyzer", "status": "active"},
            {"name": "Recommendation Trust Score", "status": "active"},
        ],
    }


def _advantage_game_contexts(platform: str, sport_filter: str | None) -> list[dict]:
    props = _fetch_props(platform, sport_filter)
    props.sort(key=lambda row: int(row.get("trending_count") or 0), reverse=True)
    games = []
    seen = set()
    for prop in props:
        game = str(prop.get("game", "")).strip()
        if not game or game in seen:
            continue
        seen.add(game)
        games.append(_game_context_payload(game, sport_filter or prop.get("league", ""), platform))
        if len(games) >= 3:
            break
    return games


def _personal_profile_payload() -> dict:
    dashboard_stats = get_dashboard()
    entry_stats = dashboard_stats.get("entries", {})
    by_sport = dashboard_stats.get("by_sport", {})
    by_platform = dashboard_stats.get("by_platform", {})
    by_stat = dashboard_stats.get("by_stat", {})
    paper = entry_stats.get("paper", {})
    best_sport = _best_group(by_sport)
    best_platform = _best_group(by_platform)
    weak_spot = _worst_group(by_sport)
    return {
        "summary": {
            "record": dashboard_stats.get("record", "0-0"),
            "profit": dashboard_stats.get("profit", 0.0),
            "roi": dashboard_stats.get("roi", 0.0),
            "recommendation_accuracy": dashboard_stats.get("recommendation_accuracy", {}),
            "paper_calibration": paper,
        },
        "strengths": [
            f"{best_sport['name']} is your strongest sport by profit/ROI." if best_sport else "Settle more entries to identify strongest sport.",
            f"{best_platform['name']} is your best platform so far." if best_platform else "Track platform on each entry to find the best app for you.",
        ],
        "weaknesses": [
            f"{weak_spot['name']} is lagging; consider paper-only until calibration improves." if weak_spot else "No weak segment detected yet.",
        ],
        "by_sport": by_sport,
        "by_platform": by_platform,
        "by_stat": by_stat,
        "recommended_settings": _recommended_user_settings(dashboard_stats, paper),
    }


def _best_group(groups: dict) -> dict | None:
    if not groups:
        return None
    name, stats = max(groups.items(), key=lambda item: (float(item[1].get("profit", 0.0)), float(item[1].get("roi", 0.0)), int(item[1].get("wins", 0))))
    return {"name": name, **stats}


def _worst_group(groups: dict) -> dict | None:
    candidates = [(name, stats) for name, stats in groups.items() if int(stats.get("wins", 0)) + int(stats.get("losses", 0)) > 0]
    if not candidates:
        return None
    name, stats = min(candidates, key=lambda item: (float(item[1].get("profit", 0.0)), float(item[1].get("roi", 0.0))))
    return {"name": name, **stats}


def _recommended_user_settings(stats: dict, paper: dict) -> dict:
    roi = float(stats.get("roi") or 0.0)
    accuracy = float((stats.get("recommendation_accuracy") or {}).get("accuracy") or 0.0)
    paper_edge = float(paper.get("calibration_edge") or 0.0)
    if roi < 0 or (accuracy and accuracy < 48):
        risk_style = "conservative"
        max_wager_pct = 2.0
    elif roi > 20 and accuracy >= 55 and paper_edge >= -8:
        risk_style = "aggressive"
        max_wager_pct = 7.5
    else:
        risk_style = "balanced"
        max_wager_pct = 5.0
    return {
        "risk_style": risk_style,
        "max_wager_pct": max_wager_pct,
        "paper_first": paper.get("decisions", 0) < 10,
        "note": "Uses your real and paper results to suggest sizing discipline.",
    }


def _game_context_payload(game: str, sport_filter: str | None, platform: str) -> dict:
    props = [
        prop for prop in _fetch_props(platform, sport_filter)
        if str(prop.get("game", "")).strip().upper() == game.strip().upper()
    ]
    analyzed = [_analyzed_feed_prop(prop) for prop in props[:30]]
    analyzed.sort(key=lambda prop: (prop["confidence"], prop["edge"], prop["trending_count"]), reverse=True)
    availability = [
        _player_availability_payload(prop["player"], prop["sport"], prop.get("team", ""), prop.get("game", ""))
        for prop in analyzed[:6]
    ]
    context_flags = []
    if len({prop.get("team") for prop in analyzed if prop.get("team")}) <= 2 and len(analyzed) >= 4:
        context_flags.append("High concentration of props in one game; watch correlation and game script.")
    if any(row["availability_score"] < 70 for row in availability):
        context_flags.append("Availability risk exists for at least one ranked player.")
    if sport_filter in {"NFL", "MLB"}:
        try:
            weather_signal = openweather.weather_signal(openweather.fetch_weather_for_game(game, sport_filter))
        except Exception:
            weather_signal = None
        if weather_signal:
            context_flags.append(weather_signal.get("message", "Weather may add variance."))
    return {
        "game": game,
        "sport": sport_filter or (analyzed[0]["sport"] if analyzed else "All Sports"),
        "platform": platform,
        "prop_count": len(analyzed),
        "ranked_players": analyzed[:8],
        "availability": availability,
        "context_flags": context_flags or ["No major game-context warning detected."],
        "correlation_note": "Avoid stacking too many same-game legs unless the correlation is intentional and priced into stake size.",
    }


def _boost_analysis_payload(payload: BoostAnalysisPayload) -> dict:
    base_projection = auto_projection(payload.original_line, 0)
    shop = _line_shop_payload(payload.player, payload.stat, payload.sport, payload.platform)
    matching = shop.get("lines", []) if shop.get("available") else []
    if matching:
        base_projection = round(sum(float(row.get("projection") or base_projection) for row in matching) / len(matching), 2)
    original_edge = calculate_edge(payload.original_line, base_projection)
    boosted_edge = calculate_edge(payload.boosted_line, base_projection)
    if payload.direction == "Under":
        original_edge *= -1
        boosted_edge *= -1
    original_confidence = calculate_confidence(original_edge)
    boosted_confidence = calculate_confidence(boosted_edge)
    original_ev = round(expected_value(payload.odds, max(0.01, min(0.99, original_confidence / 100))) * 100, 2)
    boosted_ev = round(expected_value(payload.odds, max(0.01, min(0.99, boosted_confidence / 100))) * 100, 2)
    recommendation = "Use boost" if boosted_ev > original_ev and boosted_confidence >= 52 else "Pass on boost"
    return {
        "player": payload.player,
        "sport": payload.sport,
        "stat": payload.stat,
        "direction": payload.direction,
        "projection": base_projection,
        "original": {"line": payload.original_line, "edge": round(original_edge, 2), "confidence": round(original_confidence, 1), "ev": original_ev},
        "boosted": {"line": payload.boosted_line, "edge": round(boosted_edge, 2), "confidence": round(boosted_confidence, 1), "ev": boosted_ev},
        "ev_delta": round(boosted_ev - original_ev, 2),
        "recommendation": recommendation,
        "reason": "The boost improves projected EV." if recommendation == "Use boost" else "The boost does not clear the confidence/EV threshold.",
    }


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
    suggestions = []
    suggestions.extend(suggest_entries(raw_props, sport, platform_model, limit=2, leg_count=2))
    for leg_count in (3, 4, 5):
        suggestions.extend(_best_suggestion_for_leg_count(raw_props, sport, platform_model, leg_count))

    for rank, suggestion in enumerate(suggestions[:5], start=1):
        suggestion.rank = rank
    return suggestions[:5]


def _best_suggestion_for_leg_count(raw_props: list[dict], sport: str, platform_model: Platform, leg_count: int) -> list:
    guarded = suggest_entries(
        raw_props,
        sport,
        platform_model,
        limit=1,
        leg_count=leg_count,
        max_same_team=1 if leg_count >= 4 else None,
        exclude_correlated=leg_count >= 4,
        apply_feedback=True,
    )
    if guarded:
        return guarded[:1]
    return suggest_entries(raw_props, sport, platform_model, limit=1, leg_count=leg_count)[:1]


def _props_by_platform(platform: str) -> list[tuple[Platform, list[dict]]]:
    platforms: list[tuple[Platform, list[dict]]] = []
    for platform_name in _selected_entry_platforms(platform):
        platform_model = _entry_platform_from_text(platform_name)
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
    row = {
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
        "game_time": raw.get("game_time", ""),
        "trending_count": trending_count,
        "line_movement": movement,
        "hit_rate": {
            "estimated_hit_rate": hit_rate.estimated_hit_rate,
            "last_5": hit_rate.last_5,
            "last_10": hit_rate.last_10,
            "season": hit_rate.season,
            "sample_size": hit_rate.sample_size,
            "source": hit_rate.source,
            "note": hit_rate.note,
        },
    }
    row["data_quality"] = _feed_data_quality(row, movement)
    return row


def _confirmed_props_payload(platform: str, sport_filter: str | None, limit: int = 20) -> dict:
    raw_props = _fetch_props(platform, sport_filter)
    confirmed: list[dict] = []
    confirmed_raw: list[dict] = []
    rejected = 0

    for raw in raw_props:
        analyzed = _analyzed_feed_prop(raw)
        candidate = _confirmed_prop_candidate(raw, analyzed)
        if candidate is None:
            rejected += 1
            continue
        confirmed.append(candidate)
        confirmed_raw.append(candidate["_raw"])

    confirmed.sort(key=lambda prop: (prop["confirmed_score"], prop["confidence"], prop["edge"], prop["trending_count"]), reverse=True)
    confirmed_raw_by_id = {id(row["_raw"]): row["_raw"] for row in confirmed}
    sorted_raw = [confirmed_raw_by_id[id(row["_raw"])] for row in confirmed if id(row["_raw"]) in confirmed_raw_by_id]
    selected_sport = sport_filter or _dominant_sport(confirmed)
    slate = _confirmed_slate_summary(confirmed)
    return {
        "platform": platform,
        "sport": selected_sport or "All Sports",
        "count": len(confirmed),
        "rejected_count": rejected,
        "analyzed_count": len(confirmed) + rejected,
        "slate": slate,
        "props": [{key: value for key, value in row.items() if key != "_raw"} for row in confirmed[:limit]],
        "raw_props": sorted_raw[:limit],
        "criteria": [
            "current provider row",
            "named player",
            "single-game market",
            "confirmed game time",
            "line sanity check",
            "confidence, edge, hit-rate, and data-quality context",
        ],
    }


def _confirmed_slate_summary(confirmed: list[dict]) -> list[dict]:
    sports: dict[str, dict] = {}
    for prop in confirmed:
        sport = str(prop.get("sport") or prop.get("league") or "Other").upper()
        game = str(prop.get("game") or "").strip()
        row = sports.setdefault(sport, {"sport": sport, "props": 0, "games": set()})
        row["props"] += 1
        if game:
            row["games"].add(game)
    slate = [
        {"sport": row["sport"], "props": row["props"], "games": len(row["games"])}
        for row in sports.values()
    ]
    slate.sort(key=lambda row: (row["games"], row["props"]), reverse=True)
    return slate[:6]


def _confirmed_prop_candidate(raw: dict, analyzed: dict) -> dict | None:
    platform = str(raw.get("platform") or analyzed.get("platform") or "")
    if _canonical_platform(platform) not in {"PrizePicks", "Underdog"}:
        return None
    payload = PropPayload.model_validate({
        "player": analyzed.get("player", ""),
        "team": analyzed.get("team", ""),
        "sport": analyzed.get("sport", ""),
        "stat": analyzed.get("stat", ""),
        "line": analyzed.get("line", 0),
        "projection": analyzed.get("projection"),
        "direction": analyzed.get("direction") or "Over",
        "platform": analyzed.get("platform", platform),
        "game": analyzed.get("game", ""),
        "game_time": analyzed.get("game_time", ""),
        "season_type": raw.get("season_type", ""),
        "trending_count": analyzed.get("trending_count", 0),
    })
    flags = _line_sanity_flags(payload)
    quality = analyzed.get("data_quality") or {}
    hit_rate = analyzed.get("hit_rate") or {}
    confirmation_flags = []
    if not analyzed.get("game_time"):
        confirmation_flags.append("missing game time")
    if flags:
        confirmation_flags.extend(flags)
    if float(quality.get("score") or 0) < 45:
        confirmation_flags.append("low data quality")
    if confirmation_flags:
        return None

    history_source = str(hit_rate.get("source") or "projection_model")
    history_bonus = 10 if history_source == "final_stats" else 4 if history_source != "projection_model" else 0
    score = (
        float(quality.get("score") or 0) * 0.34
        + float(analyzed.get("confidence") or 0) * 0.42
        + min(12.0, abs(float(analyzed.get("edge") or 0)) * 4)
        + history_bonus
        + min(8.0, int(analyzed.get("trending_count") or 0) / 25000)
    )
    raw_for_entry = {
        **raw,
        "projection": analyzed.get("projection"),
        "direction": analyzed.get("direction") or "Over",
        "platform": analyzed.get("platform", platform),
        "hit_rate": hit_rate,
        "confirmation": True,
        "source_signals": [{"source": "Confirmed Prop Lab", "message": "Provider line, game time, and data context confirmed before entry generation."}],
        "source_score": min(100.0, score),
    }
    return {
        **analyzed,
        "confirmed_score": round(min(100.0, score), 1),
        "confirmation": {
            "provider_current": True,
            "line_confirmed": True,
            "game_time_confirmed": True,
            "single_game_market": not _is_season_long_prop(raw),
            "history_source": history_source,
            "history_label": "true historical hit rate" if history_source == "final_stats" else "provider/API context + model estimate",
            "quality_label": quality.get("label", "partial data"),
            "quality_flags": quality.get("flags", []),
        },
        "_raw": raw_for_entry,
    }


def _dominant_sport(props: list[dict]) -> str | None:
    counts: dict[str, int] = {}
    for prop in props:
        sport = str(prop.get("sport") or "").upper()
        if sport:
            counts[sport] = counts.get(sport, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _feed_data_quality(row: dict, movement: dict) -> dict:
    score = 50.0
    flags = []
    if row.get("hit_rate", {}).get("source") != "projection_model":
        score += 20
    else:
        flags.append("model-estimated hit rate")
    if movement.get("previous") is not None:
        score += 15
    else:
        flags.append("limited line history")
    if row.get("confidence", 0) >= 60:
        score += 10
    if abs(float(row.get("edge") or 0)) < 0.5:
        score -= 8
        flags.append("thin edge")
    score = max(0, min(100, score))
    label = "strong data" if score >= 78 else "partial data" if score >= 60 else "thin data" if score >= 42 else "low reliability"
    return {"score": round(score, 1), "label": label, "flags": flags[:4]}


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
    min_confidence: float = 0.0,
    min_ev: float = -25.0,
    alert_type: str = "All",
    hide_outliers: bool = False,
) -> list[dict]:
    rows = _ev_scanner_rows(platform, sport_filter, min_ev=min_ev, limit=60, odds=odds)
    alerts = [_timing_alert_from_row(row) for row in rows]
    alerts = [alert for alert in alerts if alert is not None]
    if min_confidence:
        alerts = [alert for alert in alerts if alert["confidence"] >= min_confidence]
    if alert_type != "All":
        alerts = [alert for alert in alerts if alert["type"] == alert_type]
    if hide_outliers:
        alerts = [alert for alert in alerts if not alert.get("outlier_move")]
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
        "game_time": row.get("game_time", ""),
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
        "placed_at": iso_utc(entry.get("placed_at")),
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
        leg_source = str(final_stat.get("source") if final_stat else "").strip() or "actual_provider"
        final_status = str(status or ("played" if actual is not None else "unknown"))
        if status == "dnp":
            dnp_legs += 1
            leg_result = "DNP"
        elif actual is None and allow_estimates:
            actual = prop.get("projection")
            leg_source = "projection_estimate"
            final_status = "estimated"
            if actual is None:
                unknown = True
                leg_result = "Unknown"
            else:
                leg_result = _leg_result(actual, prop["line"], prop.get("direction", "Over"))
        elif actual is None:
            unknown = True
            leg_result = "Unknown"
        elif actual is not None:
            leg_result = _leg_result(actual, prop["line"], prop.get("direction", "Over"))
        if leg_source == "projection_estimate":
            source = "projection_estimate"
        legs.append({**prop, "actual": actual, "result": leg_result, "source": leg_source, "final_status": final_status})

    if any(leg["result"] == "Loss" for leg in legs):
        result = "Loss"
    elif dnp_legs == len(legs):
        result = "DNP"
    elif unknown and dnp_legs < len(legs):
        return {
            "id": entry["id"],
            "settled": False,
            "result": "Unknown",
            "source": "unavailable",
            "message": "Final stat data is not available yet.",
            "legs": legs,
        }
    elif any(leg["result"] == "Push" for leg in legs):
        result = "Push"
    else:
        result = "Win"

    EntryRepository.settle(entry["id"], result, dnp_legs=dnp_legs, dnp_mode=_dnp_mode(), leg_results=legs)
    return {
        "id": entry["id"],
        "settled": True,
        "result": result,
        "source": source,
        "message": "Settled from estimates." if source == "projection_estimate" else "Settled from final stats.",
        "legs": legs,
    }


def _entry_progress_payload(entry: dict, include_market_detail: bool = True) -> dict:
    legs = []
    completed = 0
    source = "unavailable"
    projected_wins = projected_losses = projected_pushes = 0
    now = utc_now().replace(tzinfo=timezone.utc)

    for prop in entry["props"]:
        final_stat = _usable_final_stat_for_entry(prop, entry)
        actual = final_stat.get("actual") if final_stat else None
        status_value = str(final_stat.get("status") if final_stat else "").strip().lower()
        timeline_status = _leg_timeline_status(prop, actual, status_value, now)
        if status_value == "dnp":
            status = "DNP"
            projected = "Push"
            completed += 1
            source = "actual_provider"
        elif actual is not None and status_value in {"live", "in_progress", "in-progress", "active"}:
            status = "Pending"
            projected = _projected_leg_status(prop)
            source = "live_provider"
            if projected == "Win":
                projected_wins += 1
            elif projected == "Loss":
                projected_losses += 1
            elif projected == "Push":
                projected_pushes += 1
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
            "timeline_status": timeline_status,
            "timeline_label": _leg_timeline_label(timeline_status),
            "final_status": status_value or ("played" if actual is not None else "pending"),
            "projected_status": projected,
            "progress_text": _leg_progress_text({**prop, "status": status, "timeline_status": timeline_status}, actual),
            "progress_percent": _leg_progress_percent(prop, actual),
            "progress_label": _leg_progress_label(prop, actual),
            "projection_progress_percent": _leg_projection_progress_percent(prop),
            "stat_bubble": _leg_stat_bubble({**prop, "timeline_status": timeline_status}, actual),
            "stat_bubble_position": _leg_stat_bubble_position(prop, actual),
            "game_time": prop.get("game_time", ""),
            "game_time_label": _game_time_label(prop.get("game_time", "")),
            "clv": _clv_for_prop(prop) if include_market_detail else _light_clv_for_prop(prop),
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
        "placed_at": iso_utc(entry.get("placed_at")),
        "average_confidence": entry["average_confidence"],
        "average_edge": entry["average_edge"],
        "completed_legs": completed,
        "total_legs": len(legs),
        "source": source,
        "tracker_status": _entry_tracker_status(legs),
        "live_result": live_result,
        "projected_result": projected_result,
        "projected_wins": projected_wins,
        "projected_losses": projected_losses,
        "projected_pushes": projected_pushes,
        "next_game_time": _next_game_time(legs),
        "next_game_time_label": _next_game_time_label(legs),
        "time_groups": _entry_time_groups(legs),
        "legs": legs,
    }


def _entry_has_stat_data(entry: dict) -> bool:
    return any(leg.get("actual") is not None for leg in entry.get("legs", []))


def _light_clv_for_prop(prop: dict) -> dict:
    return {
        "player": prop.get("player", ""),
        "sport": prop.get("sport", ""),
        "stat": prop.get("stat", ""),
        "platform": prop.get("platform", ""),
        "placed_line": float(prop.get("line") or 0),
        "current_line": None,
        "clv": None,
        "beat_market": False,
        "note": "Market-line lookup skipped for fast startup.",
    }


def _backfill_missing_game_times(entries: list[dict]) -> dict:
    candidates = [
        prop
        for entry in entries
        for prop in entry.get("props", [])
        if str(prop.get("sport", "")).upper() in {"WNBA", "NBA", "MLB", "NFL"}
    ]
    if not candidates:
        return {"provider": "espn", "updated": 0, "fetched_rows": 0, "errors": []}

    sync = refresh_game_times_for_entries(entries, lookback_days=2)
    result = EntryRepository.backfill_game_times(
        sync.get("rows", []),
        pending_only=True,
        overwrite=True,
    )
    return {
        "provider": sync.get("provider", "espn"),
        "updated": result.get("updated", 0),
        "fetched_rows": sync.get("fetched_rows", 0),
        "errors": sync.get("errors", []),
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


def _entry_tracker_status(legs: list[dict]) -> str:
    timeline_statuses = {str(leg.get("timeline_status") or "") for leg in legs}
    if not legs:
        return "No Legs"
    if any(leg.get("status") in {"Win", "Loss", "Push", "DNP"} for leg in legs):
        if any(leg.get("status") == "Pending" for leg in legs):
            return "Partially Final"
        return _entry_result_from_leg_statuses([leg["status"] for leg in legs])
    if timeline_statuses and timeline_statuses <= {"scheduled"}:
        return "Scheduled"
    if "awaiting_live" in timeline_statuses or "live" in timeline_statuses:
        return "In Progress"
    if "final_pending" in timeline_statuses:
        return "Final Stats Pending"
    if "time_unknown" in timeline_statuses:
        return "Start Time Needed"
    return "In Progress"


def _leg_timeline_status(
    prop: dict,
    actual: float | None,
    final_status: str,
    now: datetime,
) -> str:
    if final_status == "dnp":
        return "final"
    if actual is not None:
        if final_status in {"live", "in_progress", "in-progress", "active"}:
            return "live"
        return "final"

    start_time = _parse_game_time(prop.get("game_time", ""))
    if start_time is None:
        return "time_unknown"
    if now < start_time:
        return "scheduled"

    hours_since_start = (now - start_time).total_seconds() / 3600
    if hours_since_start >= _sport_final_pending_hours(prop.get("sport", "")):
        return "final_pending"
    return "awaiting_live"


def _leg_timeline_label(timeline_status: str) -> str:
    return {
        "scheduled": "Scheduled",
        "awaiting_live": "Awaiting live stats",
        "live": "Live",
        "final_pending": "Final stats pending",
        "final": "Final",
        "time_unknown": "Start time needed",
    }.get(timeline_status, "Pending")


def _sport_final_pending_hours(sport: object) -> float:
    sport_key = str(sport or "").upper()
    if sport_key in {"NBA", "WNBA", "NCAAM", "NCAAW"}:
        return 3.25
    if sport_key in {"NFL", "NCAAF"}:
        return 4.0
    if sport_key in {"MLB"}:
        return 4.5
    if sport_key in {"NHL", "MLS", "EPL", "UCL"}:
        return 3.0
    return 4.0


def _leg_progress_text(prop: dict, actual: float | None) -> str:
    if prop.get("status") == "DNP":
        return "Did not play"
    if actual is None:
        projection = prop.get("projection")
        timeline = prop.get("timeline_status")
        status_text = {
            "scheduled": "Scheduled",
            "awaiting_live": "Awaiting live stats",
            "final_pending": "Final stats pending",
            "time_unknown": "Start time needed",
        }.get(timeline, "Waiting for live stat data")
        if projection is None:
            return f"{status_text} vs line {float(prop['line']):g}"
        return f"{status_text} · Projection {float(projection):g}"
    return f"Live {actual:g} / {float(prop['line']):g}"


def _leg_progress_percent(prop: dict, actual: float | None) -> float:
    line = float(prop.get("line") or 0)
    if line <= 0 or actual is None:
        return 0.0
    return round(max(0.0, min(100.0, (float(actual) / line) * 100.0)), 1)


def _leg_progress_label(prop: dict, actual: float | None) -> str:
    if actual is None:
        return f"Waiting for live stat data / {float(prop.get('line') or 0):g}"
    return f"Live {float(actual):g} / {float(prop.get('line') or 0):g}"


def _leg_projection_progress_percent(prop: dict) -> float:
    line = float(prop.get("line") or 0)
    projection = prop.get("projection")
    if line <= 0 or projection is None:
        return 0.0
    return round(max(0.0, min(125.0, (float(projection) / line) * 100.0)), 1)


def _leg_stat_bubble(prop: dict, actual: float | None) -> str:
    line = float(prop.get("line") or 0)
    if actual is None:
        timeline = prop.get("timeline_status")
        if timeline == "scheduled":
            return "Scheduled"
        if timeline == "awaiting_live":
            return "Waiting"
        if timeline == "final_pending":
            return "Pending"
        if timeline == "time_unknown":
            return "TBD"
        return f"0 / {line:g}"
    return f"{float(actual):g} / {line:g}"


def _leg_stat_bubble_position(prop: dict, actual: float | None) -> float:
    return max(6.0, min(94.0, _leg_progress_percent(prop, actual)))


def _game_time_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "Time unavailable"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return iso_utc(parsed)


def _next_game_time(legs: list[dict]) -> str:
    dated: list[tuple[datetime, str]] = []
    undated: list[str] = []
    for leg in legs:
        raw = str(leg.get("game_time") or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            dated.append((parsed.astimezone(timezone.utc), raw))
        except ValueError:
            undated.append(raw)
    if dated:
        dated.sort(key=lambda item: item[0])
        return dated[0][1]
    return undated[0] if undated else ""


def _next_game_time_label(legs: list[dict]) -> str:
    return _game_time_label(_next_game_time(legs))


def _entry_time_groups(legs: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for leg in legs:
        raw = str(leg.get("game_time") or "").strip()
        key = raw or "unknown"
        if key not in groups:
            groups[key] = {
                "game_time": raw,
                "game_time_label": _game_time_label(raw),
                "sort_time": _game_time_sort_value(raw),
                "legs": [],
            }
        groups[key]["legs"].append(leg)

    sorted_groups = sorted(groups.values(), key=lambda group: group["sort_time"])
    for group in sorted_groups:
        group.pop("sort_time", None)
    return sorted_groups


def _game_time_sort_value(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.max.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_game_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
            "recorded_at": iso_utc(row.get("recorded_at")),
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
        platform=_entry_platform_from_text(payload.platform),
        props=[_prop_from_payload(prop, payload.platform) for prop in payload.props],
    )


def _placement_check(payload: EntryPayload) -> dict:
    checked_props: list[dict] = []
    warnings: list[str] = []
    blocks: list[str] = []
    current_by_platform: dict[str, list[dict]] = {}

    for index, prop in enumerate(payload.props, start=1):
        platform = _canonical_platform(prop.platform or payload.platform)
        if platform not in {"PrizePicks", "Underdog"}:
            checked_props.append(_placement_prop_row(index, prop, None, "skipped"))
            continue
        if platform not in current_by_platform:
            current_by_platform[platform] = _fetch_platform_props(platform)
        current = _match_current_provider_prop(prop, current_by_platform[platform])
        row = _placement_prop_row(index, prop, current, "matched" if current else "missing")
        checked_props.append(row)

        label = f"{prop.player} {prop.direction or 'Over'} {prop.stat} {prop.line}"
        if _is_season_long_prop(prop):
            blocks.append(f"{label}: season-long markets are hidden from daily placement checks.")
        if current is None:
            warnings.append(f"{label}: no current {platform} match found. Verify the line and game manually.")
            continue
        current_time = str(current.get("game_time") or "").strip()
        current_line = current.get("line")
        if not current_time:
            warnings.append(f"{label}: game time is unavailable from {platform}.")
        elif not prop.game_time:
            warnings.append(f"{label}: game time confirmed as {_short_time_label(current_time)} but was missing from the slip.")
        elif str(prop.game_time).strip() != current_time:
            warnings.append(f"{label}: game time differs from current {platform} feed ({_short_time_label(current_time)}).")
        if current_line is not None and abs(float(current_line) - float(prop.line)) >= 0.05:
            warnings.append(f"{label}: current {platform} line is {float(current_line):g}.")
        for flag in _line_sanity_flags(prop):
            warnings.append(f"{label}: {flag}")

    return {
        "ok": not blocks,
        "requires_confirmation": bool(warnings or blocks),
        "warnings": warnings,
        "blocks": blocks,
        "props": checked_props,
    }


def _placement_prop_row(index: int, prop: PropPayload, current: dict | None, status: str) -> dict:
    return {
        "index": index,
        "player": prop.player,
        "stat": prop.stat,
        "direction": prop.direction or "Over",
        "line": prop.line,
        "platform": _canonical_platform(prop.platform),
        "status": status,
        "game_time": prop.game_time,
        "current_line": current.get("line") if current else None,
        "current_game_time": current.get("game_time") if current else "",
        "current_game": current.get("game") if current else "",
    }


def _match_current_provider_prop(prop: PropPayload, current_props: list[dict]) -> dict | None:
    player_key = _match_key(prop.player)
    stat_key = _match_key(prop.stat)
    sport = prop.sport.upper()
    team = _match_key(prop.team)
    candidates = [
        current for current in current_props
        if _match_key(str(current.get("player", ""))) == player_key
        and _match_key(str(current.get("stat", ""))) == stat_key
        and str(current.get("league", "")).upper() == sport
    ]
    if not candidates:
        return None
    if team:
        team_matches = [current for current in candidates if _match_key(str(current.get("team", ""))) == team]
        if team_matches:
            candidates = team_matches
    return min(candidates, key=lambda current: abs(float(current.get("line") or 0) - float(prop.line)))


def _match_key(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _short_time_label(value: str) -> str:
    return value.replace("T", " ").replace(".000", "")


def _line_sanity_flags(prop: PropPayload) -> list[str]:
    stat = prop.stat.lower()
    line = float(prop.line)
    thresholds = [
        (("points", "pts"), 75, "line is unusually high for a points market"),
        (("assists", "asts"), 25, "line is unusually high for an assists market"),
        (("rebounds", "rebs"), 35, "line is unusually high for a rebounds market"),
        (("pra", "pts+rebs+asts", "points + rebounds + assists"), 95, "line is unusually high for a PRA market"),
        (("pass yards", "passing yards"), 475, "line is unusually high for a game passing-yards market"),
        (("receiving yards", "rec yards"), 225, "line is unusually high for a game receiving-yards market"),
        (("rush yards", "rushing yards"), 225, "line is unusually high for a game rushing-yards market"),
        (("strikeouts", "ks"), 16, "line is unusually high for a strikeouts market"),
    ]
    if _is_season_long_prop(prop):
        return ["this appears to be a season-long market, not a single-game prop"]
    return [message for needles, limit, message in thresholds if any(needle in stat for needle in needles) and line > limit]


def _reject_combined_player_props(props: list[PropPayload]) -> None:
    blocked = [
        prop for prop in props
        if is_combined_player_prop({"player": prop.player, "stat": prop.stat, "game": prop.game})
    ]
    if blocked:
        names = ", ".join(prop.player for prop in blocked[:3])
        raise HTTPException(
            status_code=400,
            detail=f"Combined-player props are not supported. Remove: {names}",
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
        platform=_entry_platform_from_text(payload.platform or entry_platform),
        game=payload.game,
        game_time=payload.game_time,
        season_type=payload.season_type,
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
    signals.extend(_summer_league_signals(payload, espn_context))
    signals.extend(_injury_signals(payload))
    signals.extend(_matchup_signals(payload))
    signals.extend(_line_movement_signals(payload))
    signals.extend(_platform_consensus_signals(payload))
    signals.extend(_sleeper_trending_signals(payload))
    signals.extend(_balldontlie_stat_signals(payload))
    signals.extend(_news_context_signals(payload))
    signals.extend(_weather_signals(payload))
    signals.extend(_calibration_feedback_signals(payload))
    signals = _apply_provider_weights(signals)

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


def _is_nba_summer_league(payload: PropPayload) -> bool:
    text = " ".join([
        payload.season_type or "",
        payload.sport or "",
        payload.game or "",
    ]).lower()
    return payload.sport.upper() == "NBA" and ("summer" in text or "nbasl" in text)


def _summer_league_signals(payload: PropPayload, espn_context: dict) -> list[dict]:
    if not _is_nba_summer_league(payload):
        return []
    sample_size = int(espn_context.get("sample_size") or 0)
    confidence_delta = -3.0 if sample_size < 2 else -1.0
    return [_signal(
        source="NBA Summer League context",
        kind="season_type",
        projection_delta=0.0,
        confidence_delta=confidence_delta,
        score=confidence_delta,
        message=(
            "NBA Summer League prop detected. EdgeIQ will still rank it from market line, trend, "
            "projection, and any ESPN/provider stats it can match, but regular NBA player history may be thin."
        ),
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
        for prop in props:
            if prop.get("final_source") == "projection_estimate" or prop.get("final_result") not in {"Win", "Loss"}:
                continue
            sport_match = str(prop.get("sport", "")).upper() == payload.sport.strip().upper()
            stat_match = str(prop.get("stat", "")).lower() == payload.stat.strip().lower()
            platform_match = str(prop.get("platform") or entry.get("platform", "")).lower() == (payload.platform or "").strip().lower()
            if sport_match and (stat_match or platform_match):
                rows.append({
                    "result": prop["final_result"],
                    "predicted": float(prop.get("confidence") or entry.get("average_confidence") or 50.0),
                })
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
        {"result": prop["final_result"], "predicted": float(prop.get("confidence") or entry.get("average_confidence") or 50.0)}
        for entry in EntryRepository.all()
        for prop in (entry.get("props") or [])
        if prop.get("final_result") in {"Win", "Loss"} and prop.get("final_source") != "projection_estimate"
    )
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


def _entry_analysis(entry: Entry, payload: EntryPayload | None = None) -> dict:
    result = entry_recommendation(entry)
    risk = calculate_entry_risk(entry.props)
    warnings = detect_correlations(entry)
    espn_notes = _entry_espn_notes(entry.props)
    risk_guardrails = _risk_guardrails(entry, payload)
    confirmation = _confirmation_checklist(entry, payload, warnings + espn_notes)
    return {
        "entry": _serialize_entry(entry),
        "recommendation": result,
        "risk": {
            "level": risk.risk.value,
            "average_confidence": round(risk.average_confidence, 2),
            "average_edge": round(risk.average_edge, 2),
            "prop_count": risk.prop_count,
        },
        "warnings": warnings + espn_notes + [guard["message"] for guard in risk_guardrails if guard["severity"] != "info"],
        "risk_guardrails": risk_guardrails,
        "confirmation_checklist": confirmation,
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


def _prop_data_quality(prop: Prop) -> dict:
    score = 45.0
    flags = []
    if prop.season_type == "summer_league":
        flags.append("NBA Summer League: limited direct player history")
        score -= 4
    if prop.espn_sample_size >= 5:
        score += 25
    elif prop.espn_sample_size > 0:
        score += 12
        flags.append("limited historical sample")
    else:
        flags.append("no matched final-stat history")
    if prop.source_signals:
        score += min(20, len(prop.source_signals) * 6)
    else:
        flags.append("few external source signals")
    if prop.auto_projected:
        score -= 5
        flags.append("projection was auto-filled")
    if abs(prop.edge) < 0.5:
        score -= 8
        flags.append("thin projected edge")
    score = max(0, min(100, score))
    if score >= 78:
        label = "strong data"
    elif score >= 60:
        label = "partial data"
    elif score >= 42:
        label = "thin data"
    else:
        label = "low reliability"
    return {"score": round(score, 1), "label": label, "flags": flags[:4]}


def _risk_guardrails(entry: Entry, payload: EntryPayload | None) -> list[dict]:
    prefs = _user_preferences()
    bankroll = float(get_dashboard().get("bankroll") or get_starting_bankroll() or 0)
    wager = float(payload.wager if payload else 0.0)
    guards: list[dict] = []
    if wager and bankroll and wager > bankroll * (prefs["max_wager_pct"] / 100):
        severity = "danger" if wager > bankroll * (max(prefs["max_wager_pct"] * 3, 25) / 100) else "warning"
        guards.append({
            "severity": severity,
            "message": f"Wager exceeds {prefs['max_wager_pct']:.1f}% of bankroll.",
        })
    if entry.prop_count >= 4 and not prefs["allow_high_risk"]:
        guards.append({"severity": "danger", "message": "Preferences block 4/5-leg high-risk entries."})
    if prefs["avoid_same_game"] and len({prop.game for prop in entry.props if prop.game}) < len([prop for prop in entry.props if prop.game]):
        guards.append({"severity": "warning", "message": "Multiple legs share a game; correlation risk is elevated."})
    if entry.average_confidence < 50:
        guards.append({"severity": "warning", "message": "Average confidence is below 50%."})
    if entry.average_edge < 0:
        guards.append({"severity": "warning", "message": "Average projected edge is negative."})
    if not guards:
        guards.append({"severity": "info", "message": "No hard bankroll or correlation guardrails triggered."})
    return guards


def _confirmation_checklist(entry: Entry, payload: EntryPayload | None, warnings: list[str]) -> list[dict]:
    props = entry.props
    has_summer_league = any(prop.season_type == "summer_league" for prop in props)
    availability_rows = [
        _player_availability_payload(prop.player.name, prop.player.sport, prop.player.team, prop.game)
        for prop in props
    ]
    availability_risk = [row for row in availability_rows if row["availability_score"] < 70]
    return [
        {
            "label": "Injury/news context",
            "status": "warning" if availability_risk else "checked" if any(prop.source_signals for prop in props) else "needs review",
            "detail": f"{availability_risk[0]['player']} availability is {availability_risk[0]['status']}." if availability_risk else "External source signals found." if any(prop.source_signals for prop in props) else "No external news/injury signals matched.",
        },
        {
            "label": "Historical data",
            "status": "warning" if has_summer_league and not any(prop.espn_sample_size for prop in props) else "checked" if any(prop.espn_sample_size for prop in props) else "thin",
            "detail": "NBA Summer League markets can have thin direct player history; EdgeIQ used market/projection context where stat rows were unavailable." if has_summer_league else f"{sum(1 for prop in props if prop.espn_sample_size)} legs have final-stat history.",
        },
        {
            "label": "Correlation",
            "status": "warning" if warnings else "checked",
            "detail": warnings[0] if warnings else "No correlation warning detected.",
        },
        {
            "label": "Bankroll sizing",
            "status": "paper" if payload and payload.entry_mode == "paper" else "checked" if payload and payload.wager > 0 else "needs wager",
            "detail": "Paper entry: bankroll and profit tracking are disabled." if payload and payload.entry_mode == "paper" else f"{payload.wager:.2f} wager entered." if payload and payload.wager > 0 else "Enter wager before placement.",
        },
    ]


def _entry_audit_snapshot(entry: Entry, payload: EntryPayload, analysis: dict) -> dict:
    return {
        "created_at": iso_utc(utc_now()),
        "platform": payload.platform,
        "wager": payload.wager,
        "multiplier": payload.multiplier,
        "entry_mode": payload.entry_mode,
        "recommended_by_app": payload.recommended_by_app,
        "recommendation": analysis.get("recommendation", {}),
        "risk": analysis.get("risk", {}),
        "warnings": analysis.get("warnings", []),
        "source_fusion": analysis.get("source_fusion", {}),
        "confirmation_checklist": analysis.get("confirmation_checklist", []),
        "props": analysis.get("entry", {}).get("props", []),
    }


def _safe_json_loads(value: str) -> dict:
    try:
        return json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}


def _user_preferences() -> dict:
    defaults = {
        "risk_style": "balanced",
        "preferred_legs": "2-3",
        "allow_high_risk": True,
        "avoid_same_game": True,
        "max_wager_pct": 5.0,
        "default_platform": "PrizePicks",
        "default_sport": "All Sports",
        "display_name": "Joshua",
    }
    stored = _safe_json_loads(SettingsRepository.get("user_preferences", ""))
    return {**defaults, **stored}


def _bankroll_strategy() -> dict:
    defaults = {
        "mode": "balanced",
        "unit_size": 10.0,
        "max_wager_pct": 5.0,
        "paper_first": False,
    }
    stored = _safe_json_loads(SettingsRepository.get("bankroll_strategy", ""))
    strategy = {**defaults, **stored}
    strategy["mode"] = strategy["mode"] if strategy["mode"] in {"flat", "conservative", "balanced", "aggressive", "kelly", "paper"} else "balanced"
    strategy["unit_size"] = max(0.0, float(strategy.get("unit_size") or defaults["unit_size"]))
    strategy["max_wager_pct"] = max(0.1, min(100.0, float(strategy.get("max_wager_pct") or defaults["max_wager_pct"])))
    strategy["paper_first"] = bool(strategy.get("paper_first"))
    return strategy


def _watchlist_items() -> list[dict]:
    rows = _safe_json_loads(SettingsRepository.get("prop_watchlist", ""))
    if isinstance(rows, dict):
        rows = rows.get("items", [])
    if not isinstance(rows, list):
        return []
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("player"):
            continue
        item = {
            "player": str(row.get("player", "")).strip(),
            "sport": str(row.get("sport", "All Sports") or "All Sports"),
            "stat": str(row.get("stat", "") or ""),
            "platform": str(row.get("platform", "PrizePicks") or "PrizePicks"),
            "direction": row.get("direction") if row.get("direction") in {"Over", "Under", "Any"} else "Any",
            "target_line": row.get("target_line"),
            "alert_when": row.get("alert_when") if row.get("alert_when") in {"at_or_better", "moves_by", "available"} else "at_or_better",
            "move_threshold": max(0.0, float(row.get("move_threshold") or 1.0)),
            "note": str(row.get("note", "") or ""),
        }
        item["id"] = row.get("id") or _watchlist_item_id(item)
        normalized.append(item)
    return normalized


def _watchlist_item_id(item: dict) -> str:
    key = "|".join([
        str(item.get("player", "")).strip().lower(),
        str(item.get("sport", "")).strip().upper(),
        str(item.get("stat", "")).strip().lower(),
        str(item.get("platform", "")).strip().lower(),
        str(item.get("direction", "")).strip().lower(),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _watchlist_alerts(items: list[dict] | None = None) -> list[dict]:
    items = items if items is not None else _watchlist_items()
    alerts = []
    for item in items:
        sport_filter = None if item.get("sport") == "All Sports" else str(item.get("sport", "")).upper()
        candidates = _fetch_props(item.get("platform", "PrizePicks"), sport_filter)
        for raw in candidates:
            if item["player"].lower() not in str(raw.get("player", "")).lower():
                continue
            if item.get("stat") and item["stat"].lower() != str(raw.get("stat", "")).lower():
                continue
            analyzed = _analyzed_feed_prop(raw)
            direction = item.get("direction", "Any")
            target = item.get("target_line")
            triggered = item.get("alert_when") == "available"
            reason = "Watched prop is available."
            if target not in (None, ""):
                target = float(target)
                line = float(analyzed.get("line") or 0.0)
                if direction == "Under":
                    triggered = line >= target
                    reason = f"Under line is at or above target {target:g}."
                else:
                    triggered = line <= target
                    reason = f"Over line is at or below target {target:g}."
            if item.get("alert_when") == "moves_by":
                change = abs(float((analyzed.get("line_movement") or {}).get("change") or 0.0))
                triggered = change >= float(item.get("move_threshold") or 1.0)
                reason = f"Line moved {change:g}, meeting the watch threshold."
            if triggered:
                alerts.append({
                    "id": item["id"],
                    "player": analyzed["player"],
                    "sport": analyzed["sport"],
                    "stat": analyzed["stat"],
                    "direction": direction,
                    "platform": analyzed["platform"],
                    "line": analyzed["line"],
                    "confidence": analyzed["confidence"],
                    "edge": analyzed["edge"],
                    "reason": reason,
                    "prop": analyzed,
                })
                break
    alerts.sort(key=lambda row: (row["confidence"], row["edge"]), reverse=True)
    return alerts[:20]


def _provider_weights() -> dict:
    defaults = {
        "ESPN form": 1.0,
        "ESPN injuries": 1.2,
        "WNBA defense": 0.8,
        "Line movement": 1.15,
        "Platform consensus": 1.1,
        "Sleeper trends": 0.85,
        "Ball Don't Lie stats": 0.95,
        "NewsAPI": 0.8,
        "OpenWeather": 0.75,
        "Calibration feedback": 1.25,
    }
    stored = _safe_json_loads(SettingsRepository.get("provider_weights", ""))
    merged = {**defaults, **stored}
    return {key: max(0.0, min(2.0, float(value))) for key, value in merged.items()}


def _apply_provider_weights(signals: list[dict]) -> list[dict]:
    weights = _provider_weights()
    weighted = []
    for signal in signals:
        weight = float(weights.get(signal.get("source", ""), 1.0))
        row = dict(signal)
        row["provider_weight"] = round(weight, 2)
        row["projection_delta"] = round(float(row.get("projection_delta", 0.0)) * weight, 3)
        row["confidence_delta"] = round(float(row.get("confidence_delta", 0.0)) * weight, 3)
        row["score"] = round(float(row.get("score", 0.0)) * weight, 3)
        weighted.append(row)
    return weighted


def _data_health_payload() -> dict:
    providers = [
        _provider_health_row("PrizePicks", "props", configured=True, key_env=""),
        _provider_health_row("Underdog", "props", configured=True, key_env=""),
        _sleeper_health_row(),
        _provider_health_row("OpenAI", "AI recommendations/screenshots", configured=bool(os.getenv("OPENAI_API_KEY")), key_env="OPENAI_API_KEY"),
        _provider_health_row("SportsDataIO", "final stats/injuries", configured=bool(os.getenv("SPORTSDATAIO_API_KEY")), key_env="SPORTSDATAIO_API_KEY"),
        _provider_health_row("NewsAPI", "news context", configured=bool(os.getenv("NEWSAPI_KEY")), key_env="NEWSAPI_KEY"),
        _provider_health_row("OpenWeather", "outdoor weather", configured=bool(os.getenv("OPENWEATHER_API_KEY")), key_env="OPENWEATHER_API_KEY"),
        _provider_health_row("Ball Don't Lie", "player stats", configured=bool(os.getenv("BALLDONTLIE_API_KEY") or os.getenv("BALLDONTLIE_PROPS_URL")), key_env="BALLDONTLIE_API_KEY"),
        _provider_health_row("ESPN public", "final stats/injuries", configured=True, key_env=""),
        _provider_health_row("NBA Stats", "Summer League final stats", configured=True, key_env=""),
    ]
    weights = _provider_weights()
    connected = sum(1 for provider in providers if provider["status"] in {"connected", "available"})
    warnings = [provider for provider in providers if provider["status"] in {"missing_key", "not_configured"}]
    return {
        "providers": providers,
        "provider_weights": weights,
        "summary": {
            "connected": connected,
            "total": len(providers),
            "warnings": len(warnings),
            "last_daily_refresh": SettingsRepository.get("last_daily_refresh", ""),
        },
    }


def _provider_health_row(name: str, purpose: str, configured: bool, key_env: str) -> dict:
    has_key = bool(os.getenv(key_env, "").strip()) if key_env else configured
    if configured and has_key:
        status = "connected" if key_env else "available"
    elif configured and key_env and not has_key:
        status = "missing_key"
    else:
        status = "not_configured"
    return {
        "name": name,
        "purpose": purpose,
        "status": status,
        "configured": bool(configured),
        "key_env": key_env,
        "has_key": has_key,
        "message": _provider_health_message(name, status, key_env),
    }


def _provider_health_message(name: str, status: str, key_env: str) -> str:
    if status in {"connected", "available"}:
        return f"{name} is available to EdgeIQ."
    if status == "missing_key":
        return f"Set {key_env} to enable {name}."
    return f"{name} is not configured yet."


def _sleeper_health_row() -> dict:
    status = sleeper.public_api_status()
    player_cache = status["player_cache"]
    cache_label = "fresh" if player_cache["fresh"] else "not warmed"
    if player_cache["cached"] and not player_cache["fresh"]:
        cache_label = "stale"
    return {
        "name": "Sleeper",
        "purpose": "public NFL player metadata/trends; optional prop-feed import",
        "status": "available",
        "configured": True,
        "key_env": "",
        "has_key": False,
        "auth_required": False,
        "read_only": True,
        "props_configured": status["props_configured"],
        "player_cache": player_cache,
        "message": (
            f"No API key needed. Public read-only trends are available; "
            f"player cache is {cache_label}. "
            f"{'Prop feed configured.' if status['props_configured'] else 'Configure a Sleeper prop feed only if you want Sleeper lines.'}"
        ),
    }


def _refresh_schedule_payload() -> dict:
    defaults = {
        "morning_scan": "08:00",
        "injury_refresh": "11:00",
        "line_snapshots": "*/30",
        "result_check": "23:30",
        "nightly_calibration": "02:00",
        "enabled": True,
    }
    schedule = {**defaults, **_safe_json_loads(SettingsRepository.get("refresh_schedule", ""))}
    jobs = [
        {"name": "Morning board scan", "time": schedule["morning_scan"], "action": "Refresh props, command center, timing alerts."},
        {"name": "Injury/news refresh", "time": schedule["injury_refresh"], "action": "Update availability, injuries, news context."},
        {"name": "Line movement snapshots", "time": schedule["line_snapshots"], "action": "Record prop lines for CLV and timing alerts."},
        {"name": "Post-game result check", "time": schedule["result_check"], "action": "Auto-check pending entries against final stats."},
        {"name": "Nightly calibration", "time": schedule["nightly_calibration"], "action": "Rebuild model health and confidence calibration."},
    ]
    return {"schedule": schedule, "jobs": jobs, "last_run": SettingsRepository.get("last_daily_refresh", "")}


def _notification_payload() -> dict:
    notices = []
    health = _data_health_payload()
    for provider in health["providers"]:
        if provider["status"] in {"missing_key", "not_configured"} and provider["name"] in {"OpenAI", "SportsDataIO", "NewsAPI", "OpenWeather"}:
            notices.append({
                "type": "Data Health",
                "severity": "warning",
                "title": f"{provider['name']} not fully connected",
                "message": provider["message"],
            })
    for entry in _entry_progress_payloads_for_notifications():
        if entry["live_result"] in {"Win", "Loss", "Push"}:
            notices.append({
                "type": "Entry Result",
                "severity": "positive" if entry["live_result"] == "Win" else "danger" if entry["live_result"] == "Loss" else "neutral",
                "title": f"Entry #{entry['id']} currently {entry['live_result']}",
                "message": f"{entry['completed_legs']}/{entry['total_legs']} legs final.",
            })
    try:
        alerts = _market_timing_alert_rows("PrizePicks", None, 5, -110, 60, 5, "All", True)
    except Exception:
        alerts = []
    for alert in alerts[:3]:
        notices.append({
            "type": "Market Timing",
            "severity": alert["severity"],
            "title": f"{alert['type']}: {alert['player']}",
            "message": alert["reason"],
        })
    return {"notifications": notices[:12], "count": min(len(notices), 12)}


def _entry_progress_payloads_for_notifications() -> list[dict]:
    try:
        return [_entry_progress_payload(entry) for entry in EntryRepository.pending()]
    except Exception:
        return []


def _player_availability_payload(player: str, sport: str, team: str = "", game: str = "") -> dict:
    injury = None
    try:
        injury = is_injured(player, fetch_injuries(sport))
    except Exception:
        injury = None
    news_terms = []
    try:
        news_terms = newsapi.risk_terms(newsapi.fetch_context(f'"{player}" {sport} {team}', days=7, page_size=5))
    except Exception:
        news_terms = []
    score = 86.0
    status = "Likely Active"
    factors = []
    if injury:
        text = str(injury.get("status", "")).lower()
        factors.append(f"Injury feed: {injury.get('status')} {injury.get('detail', '')}".strip())
        if "out" in text or "doubtful" in text:
            score -= 70
            status = "High DNP Risk"
        elif "questionable" in text or "day-to-day" in text:
            score -= 35
            status = "Questionable"
        else:
            score -= 10
            status = "Monitor"
    if news_terms:
        factors.append(f"News context mentions {', '.join(news_terms)}.")
        if any(term in news_terms for term in {"injury", "rest"}):
            score -= 18
            status = "Monitor" if status == "Likely Active" else status
    if sport.upper() in {"MLB", "NFL"} and game:
        try:
            weather_signal = openweather.weather_signal(openweather.fetch_weather_for_game(game, sport))
        except Exception:
            weather_signal = None
        if weather_signal:
            factors.append(weather_signal.get("message", "Weather may add variance."))
            score -= 5
    score = round(max(0.0, min(100.0, score)), 1)
    if not factors:
        factors.append("No injury/news availability risks matched.")
    return {"player": player, "sport": sport, "team": team, "game": game, "availability_score": score, "status": status, "factors": factors}


def _accuracy_lab_payload() -> dict:
    entries = EntryRepository.all()
    settled = [entry for entry in entries if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss", "Push"}]
    audits = [_safe_json_loads(entry.get("audit_snapshot", "")) for entry in entries if entry.get("audit_snapshot")]
    confidence_rows = _accuracy_confidence_rows(settled)
    return {
        "summary": {
            "settled_entries": len(settled),
            "audit_snapshots": len(audits),
            "recommended_settled": sum(1 for entry in settled if entry.get("recommended_by_app")),
        },
        "by_grade": EntryRepository._group_by_key(settled, lambda entry: entry.get("grade") or "Ungraded"),
        "by_sport": EntryRepository._group_by_key(settled, EntryRepository._primary_sport),
        "by_platform": EntryRepository._group_by_key(settled, lambda entry: entry.get("platform") or "Unknown"),
        "confidence_buckets": confidence_rows,
        "audit_trail": [
            {
                "entry_id": entry["id"],
                "placed_at": iso_utc(entry.get("placed_at")),
                "result": entry.get("result", ""),
                "grade": entry.get("grade", ""),
                "line_snapshot_count": len(_safe_json_loads(entry.get("audit_snapshot", "")).get("props", [])),
                "recommendation": _safe_json_loads(entry.get("audit_snapshot", "")).get("recommendation", {}),
            }
            for entry in entries[:20]
            if entry.get("audit_snapshot")
        ],
    }


def _accuracy_confidence_rows(entries: list[dict]) -> list[dict]:
    buckets = [
        ("0-49", 0, 49.999),
        ("50-59", 50, 59.999),
        ("60-69", 60, 69.999),
        ("70-100", 70, 100),
    ]
    rows = []
    for label, low, high in buckets:
        bucket = [
            entry for entry in entries
            if low <= float(entry.get("average_confidence") or 0) <= high and entry.get("result") in {"Win", "Loss"}
        ]
        wins = sum(1 for entry in bucket if entry.get("result") == "Win")
        rows.append({
            "label": label,
            "entries": len(bucket),
            "wins": wins,
            "losses": len(bucket) - wins,
            "win_pct": round((wins / len(bucket) * 100) if bucket else 0.0, 1),
            "avg_confidence": round(sum(float(entry.get("average_confidence") or 0) for entry in bucket) / len(bucket), 1) if bucket else 0.0,
        })
    return rows


def _serialize_entry(entry: Entry) -> dict:
    return {
        "platform": entry.platform.value,
        "average_confidence": round(entry.average_confidence, 2),
        "average_edge": round(entry.average_edge, 2),
        "props": [_serialize_prop(prop) for prop in entry.props],
    }


def _serialize_prop(prop: Prop) -> dict:
    quality = _prop_data_quality(prop)
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
        "game_time": prop.game_time,
        "season_type": prop.season_type,
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
        "data_quality": quality,
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
        "placed_at": iso_utc(entry.get("placed_at")),
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
        "source": bet.source,
        "source_entry_id": bet.source_entry_id,
        "entry_mode": bet.entry_mode,
    }


def _serialize_bet_history_entry(entry: dict) -> dict:
    props = entry.get("props") or []
    calibration_legs = [
        prop for prop in props
        if prop.get("final_result") in {"Win", "Loss"} and prop.get("final_source") != "projection_estimate"
    ]
    return {
        "id": entry.get("id"),
        "platform": entry.get("platform", ""),
        "entry_mode": entry.get("entry_mode", "real"),
        "result": entry.get("result", ""),
        "status": entry.get("status", ""),
        "wager": entry.get("wager", 0.0),
        "multiplier": entry.get("multiplier", 1.0),
        "profit": entry.get("profit", 0.0),
        "placed_at": iso_utc(entry.get("placed_at")),
        "settled_at": iso_utc(entry.get("settled_at")),
        "average_confidence": entry.get("average_confidence", 0.0),
        "average_edge": entry.get("average_edge", 0.0),
        "calibration_legs": len(calibration_legs),
        "props": [
            {
                "player": prop.get("player", ""),
                "team": prop.get("team", ""),
                "sport": prop.get("sport", ""),
                "stat": prop.get("stat", ""),
                "direction": prop.get("direction", "Over"),
                "line": prop.get("line"),
                "projection": prop.get("projection"),
                "actual": prop.get("actual"),
                "result": prop.get("final_result") or "Pending",
                "source": prop.get("final_source") or "unmatched",
                "status": prop.get("final_status") or "",
                "game": prop.get("game", ""),
                "game_time": prop.get("game_time", ""),
                "confidence": prop.get("confidence"),
            }
            for prop in props
        ],
    }


def _platform_from_text(value: str) -> Platform:
    for platform in Platform:
        if platform.value.lower() == (value or "").lower():
            return platform
    return Platform.PRIZEPICKS


def _stat_from_text(value: str) -> StatType:
    return stat_type_from_text(value)
