from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import data.providers.balldontlie as balldontlie
import data.providers.nba_summer_league as nba_summer_league
import data.providers.newsapi as newsapi
import data.providers.openweather as openweather
import data.providers.pandascore as pandascore
import data.providers.prizepicks as prizepicks
import data.providers.sleeper as sleeper
import data.providers.sportsdataio as sportsdataio
import data.providers.underdog as underdog
from analytics.backtesting import backtest_summary
from analytics.correlation import detect_correlations, estimate_correlation_matrix
from analytics.defense_vs_position import analyze_matchup
from analytics.edgeiq_model import MODEL_VERSION as EDGEIQ_LOCAL_MODEL_VERSION
from analytics.edgeiq_model import compose_parlay_response as local_parlay_response
from analytics.edgeiq_model import model_card as local_model_card
from analytics.entry_recommendation import recommendation as entry_recommendation
from analytics.entry_suggestions import suggest_entries
from analytics.ev import decimal_odds, expected_value, sportsbook_probability
from analytics.hierarchical_calibration import calibrate_probability
from analytics.hit_rate import estimate_hit_rate
from analytics.kelly import breakeven_probability, half_kelly, kelly_fraction, suggested_wager
from analytics.outcome_learning import outcome_comparison
from analytics.pickem_payouts import payout_analysis
from analytics.prediction_evidence import deduplicate_outcomes
from analytics.probabilistic_forecast import forecast_prop
from analytics.projection import auto_projection
from analytics.prop_metrics import calculate_confidence, calculate_directional_edge, calculate_edge
from analytics.push_risk import push_risk
from analytics.recommendation import recommendation as ev_recommendation
from analytics.risk import calculate_entry_risk
from data.providers.espn import (
    fetch_game_times,
    refresh_final_stats_for_entries,
    refresh_game_times_for_entries,
    refresh_live_stats_for_entries,
)
from data.providers.final_stats import find_actual_stat, find_final_stat, import_final_stats
from data.providers.generic_props import normalize_props
from data.providers.injury_feed import fetch_injuries, is_injured
from data.providers.prop_filters import is_combined_player_prop
from models.bet import Bet
from models.entry import Entry
from models.platform import Platform
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType
from repository.bet_repository import BetRepository
from repository.database import initialize_database
from repository.repositories.bankroll_transaction_repository import BankrollTransactionRepository
from repository.repositories.board_offer_repository import BoardOfferRepository
from repository.repositories.entry_repository import EntryRepository
from repository.repositories.final_stats_repository import FinalStatsRepository
from repository.repositories.line_history_repository import LineHistoryRepository
from repository.repositories.model_rehabilitation_repository import ModelRehabilitationRepository
from repository.repositories.plausibility_rejection_repository import PlausibilityRejectionRepository
from repository.repositories.player_identity_repository import PlayerIdentityRepository
from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository
from repository.repositories.research_evidence_repository import ResearchEvidenceRepository
from repository.repositories.settings_repository import SettingsRepository
from repository.repositories.settlement_audit_repository import SettlementAuditRepository
from services import odds as sportsbook_odds
from services.betting import potential_profit
from services.dashboard import get_dashboard, get_starting_bankroll, set_starting_bankroll
from services.data_management import backup_database, export_database
from services.ollama_client import (
    ollama_chat,
    ollama_model,
    ollama_status,
    ollama_vision_structured,
)
from services.operation_lock import named_operation_lock
from utils.entity_normalization import canonical_matchup_key, canonical_person_key, same_person
from utils.market_validation import is_partial_game_market
from utils.prop_plausibility import prop_line_plausibility
from utils.stat_normalization import canonical_stat_label, stat_type_from_text
from utils.stat_normalization import stat_key as canonical_stat_key
from utils.time import iso_utc, utc_now
from web.application.advantage_service import advantage_center_payload as build_advantage_center_payload
from web.application.advantage_service import advantage_game_contexts as build_advantage_game_contexts
from web.application.alert_delivery_service import deliver_alert as deliver_configured_alert
from web.application.alert_delivery_service import delivery_hooks as configured_delivery_hooks
from web.application.bankroll_service import (
    bankroll_transactions_payload as build_bankroll_transactions_payload,
)
from web.application.bankroll_service import (
    save_bankroll_transaction_payload as build_save_bankroll_transaction_payload,
)
from web.application.bankroll_service import (
    update_bankroll_payload as build_update_bankroll_payload,
)
from web.application.bankroll_service import (
    update_bankroll_strategy_payload as build_update_bankroll_strategy_payload,
)
from web.application.bankroll_service import (
    update_loss_protection_payload as build_update_loss_protection_payload,
)
from web.application.briefing_service import (
    append_daily_scan_log as append_briefing_scan_log,
)
from web.application.briefing_service import (
    cached_daily_briefing_payload as build_cached_daily_briefing_payload,
)
from web.application.briefing_service import (
    daily_briefing_cache_is_fresh as briefing_cache_is_fresh,
)
from web.application.briefing_service import (
    daily_briefing_cache_key as briefing_cache_key,
)
from web.application.briefing_service import daily_scan_status_payload as build_daily_scan_status_payload
from web.application.briefing_service import daily_scan_steps as build_daily_scan_steps
from web.application.briefing_service import daily_scan_summary as build_daily_scan_summary
from web.application.briefing_service import friendly_scan_status
from web.application.briefing_service import new_daily_scan as build_new_daily_scan
from web.application.briefing_service import recover_interrupted_daily_scan as recover_briefing_scan
from web.application.briefing_service import run_daily_briefing_scan as run_briefing_scan
from web.application.briefing_service import save_daily_scan_status as persist_daily_scan_status
from web.application.briefing_service import update_daily_scan as update_briefing_scan
from web.application.copilot_service import copilot_query_payload as build_copilot_query_payload
from web.application.copilot_service import explain_recommendation_payload as build_explain_recommendation_payload
from web.application.copilot_service import model_evaluation_payload as build_model_evaluation_payload
from web.application.entry_creation_service import (
    analyze_entry_payload as build_analyze_entry_payload,
)
from web.application.entry_creation_service import (
    payout_analysis_payload as build_entry_payout_analysis_payload,
)
from web.application.entry_creation_service import (
    place_entry_payload as build_place_entry_payload,
)
from web.application.entry_creation_service import (
    validated_call,
)
from web.application.import_service import analyze_upload_payload as build_analyze_upload_payload
from web.application.import_service import deduplicate_uploaded_props
from web.application.import_service import import_betting_history_payload as build_import_betting_history_payload
from web.application.import_service import import_wizard_payload as build_import_wizard_payload
from web.application.import_service import parse_betting_history as _parse_betting_history
from web.application.intelligence_service import ai_status_payload as build_ai_status_payload
from web.application.intelligence_service import entry_review_payload as build_entry_review_payload
from web.application.intelligence_service import ev_analysis_payload as build_ev_analysis_payload
from web.application.intelligence_service import game_context_response as build_game_context_response
from web.application.intelligence_service import parlay_chat_payload as build_parlay_chat_payload
from web.application.intelligence_service import projection_assist_payload as build_projection_assist_payload
from web.application.intelligence_service import trending_games_response as build_trending_games_response
from web.application.operations_service import delete_watchlist_payload as build_delete_watchlist_payload
from web.application.operations_service import run_daily_refresh_payload as build_run_daily_refresh_payload
from web.application.operations_service import save_watchlist_payload as build_save_watchlist_payload
from web.application.operations_service import sync_payload as build_sync_payload
from web.application.operations_service import update_dnp_payload as build_update_dnp_payload
from web.application.operations_service import update_preferences_payload as build_update_preferences_payload
from web.application.operations_service import (
    update_provider_weights_payload as build_update_provider_weights_payload,
)
from web.application.operations_service import (
    update_refresh_schedule_payload as build_update_refresh_schedule_payload,
)
from web.application.operations_service import watchlist_alerts_payload as build_watchlist_alerts_payload
from web.application.operations_service import watchlist_payload as build_watchlist_payload
from web.application.player_hit_ranking_service import player_stat_hit_leaderboard
from web.application.player_service import player_detail_payload as build_player_detail_payload
from web.application.player_service import player_hit_rate_payload as build_player_hit_rate_payload
from web.application.player_service import player_identity_payload as build_player_identity_payload
from web.application.player_service import player_line_movement_payload as build_player_line_movement_payload
from web.application.portfolio_service import active_portfolio_monitor_payload as build_active_portfolio_monitor_payload
from web.application.portfolio_service import bets_payload as build_bets_payload
from web.application.portfolio_service import personal_profile_payload as build_personal_profile_payload
from web.application.portfolio_service import portfolio_intelligence_payload as build_portfolio_intelligence_payload
from web.application.portfolio_service import portfolio_ranked_suggestions as build_portfolio_ranked_suggestions
from web.application.portfolio_service import refresh_portfolio_market_payload as build_refresh_portfolio_market_payload
from web.application.portfolio_service import save_bet_payload as build_save_bet_payload
from web.application.provider_health_service import (
    age_minutes as _age_minutes,
)
from web.application.provider_health_service import (
    build_data_health_payload,
)
from web.application.provider_health_service import (
    provider_status_key as _provider_status_key,
)
from web.application.recommendation_policy import recommendation_eligibility
from web.application.recommendation_service import (
    cached_command_center_payload as build_cached_command_center_payload,
)
from web.application.recommendation_service import (
    confirmed_entry_suggestions_payload as build_confirmed_entry_suggestions_payload,
)
from web.application.recommendation_service import crazy_six_payload as build_crazy_six_payload
from web.application.recommendation_service import (
    dashboard_parlay_payload as build_dashboard_parlay_payload,
)
from web.application.recommendation_service import (
    entry_suggestions_payload as build_entry_suggestions_payload,
)
from web.application.recommendation_service import (
    optimized_entries_payload as build_optimized_entries_payload,
)
from web.application.recommendation_service import top_props_payload as build_top_props_payload
from web.application.recommendation_service import trending_props_payload as build_trending_props_payload
from web.application.research_service import persist_player_research, research_evidence_payload
from web.application.results_service import (
    accuracy_lab_payload as build_accuracy_lab_payload,
)
from web.application.results_service import (
    backtest_payload as build_backtest_payload,
)
from web.application.results_service import (
    model_health_payload as build_model_health_payload,
)
from web.application.results_service import (
    performance_payload as build_performance_payload,
)
from web.application.settlement_service import (
    backfill_final_stats_payload as build_backfill_final_stats_payload,
)
from web.application.settlement_service import (
    classify_default_wagers_payload as build_classify_default_wagers_payload,
)
from web.application.settlement_service import (
    entry_progress_payload as build_entry_progress_payload,
)
from web.application.settlement_service import (
    pending_entries_payload as build_pending_entries_payload,
)
from web.application.settlement_service import (
    recheck_final_stats_payload as build_recheck_final_stats_payload,
)
from web.application.settlement_service import (
    recheck_final_stats_preview_payload as build_recheck_final_stats_preview_payload,
)
from web.application.settlement_service import (
    settle_entry_payload as build_settle_entry_payload,
)
from web.routers.advantage import (
    AdvantageDependencies,
    advantage_center,
    configure_advantage_router,
)
from web.routers.advantage import router as advantage_router
from web.routers.bankroll import (
    BankrollDependencies,
    bankroll_strategy,
    bankroll_transactions,
    configure_bankroll_router,
    loss_protection,
    loss_review,
    save_bankroll_transaction,
    update_bankroll,
    update_bankroll_strategy,
    update_loss_protection,
)
from web.routers.bankroll import router as bankroll_router
from web.routers.briefing import (
    BriefingDependencies,
    configure_briefing_router,
    daily_briefing,
    daily_briefing_scan_status,
    start_daily_briefing_scan,
)
from web.routers.briefing import router as briefing_router
from web.routers.entries import (
    EntryDependencies,
    analyze_entry,
    configure_entry_router,
    entry_handoff,
    entry_payout_analysis,
    place_entry,
    placement_check,
    platform_value_check,
    share_entry,
    shared_entry,
    shared_entry_page,
)
from web.routers.entries import (
    router as entry_router,
)
from web.routers.experience import router as experience_router
from web.routers.intelligence import (
    IntelligenceDependencies,
    ai_copilot,
    ai_entry_review,
    ai_parlay_chat,
    ai_status,
    analyze_ev,
    configure_intelligence_router,
    evaluate_local_model,
    explain_recommendation,
    game_context,
    projection_assist,
    trending_games,
)
from web.routers.intelligence import router as intelligence_router
from web.routers.market import (
    MarketDependencies,
    boost_analysis,
    clv_report,
    configure_market_router,
    ev_scanner,
    hedge_calculator,
    line_shop,
    market_timing_alerts,
    middle_calculator,
    player_market_odds,
    sharp_consensus,
)
from web.routers.market import (
    router as market_router,
)
from web.routers.operations import (
    OperationsDependencies,
    alert_delivery_settings,
    configure_operations_router,
    delete_watchlist_item,
    deploy_readiness,
    dnp_setting,
    notifications,
    provider_weights,
    refresh_schedule,
    run_daily_refresh,
    run_sync,
    save_watchlist_item,
    sportsbook_integrations,
    test_alert_delivery,
    update_alert_delivery_settings,
    update_dnp_setting,
    update_provider_weights,
    update_refresh_schedule,
    update_user_preferences,
    user_preferences,
    watchlist,
    watchlist_alerts,
)
from web.routers.operations import router as operations_router
from web.routers.players import (
    PlayerDependencies,
    configure_player_router,
    player_availability,
    player_detail,
    player_hit_rate,
    player_identity,
    player_line_movement,
    player_research,
)
from web.routers.players import router as player_router
from web.routers.portfolio import (
    PortfolioDependencies,
    bets,
    configure_portfolio_router,
    dashboard,
    personal_profile,
    portfolio_intelligence,
    refresh_portfolio_market_data,
    save_bet,
)
from web.routers.portfolio import router as portfolio_router
from web.routers.providers import (
    ProviderDependencies,
    configure_provider_router,
    data_health,
    sleeper_status,
)
from web.routers.providers import (
    router as provider_router,
)
from web.routers.recommendations import (
    RecommendationDependencies,
    auto_paper_calibration,
    configure_recommendation_router,
    confirmed_entry_suggestions,
    confirmed_props,
    crazy_six_suggestion,
    dashboard_command_center,
    dashboard_parlay,
    entry_suggestions,
    opportunity_feed,
    optimize_entries,
    top_props,
)
from web.routers.recommendations import router as recommendation_router
from web.routers.results import (
    ResultsDependencies,
    accuracy_lab,
    backtest,
    configure_results_router,
    create_database_backup,
    create_database_export,
    model_health,
    performance,
    refresh_calibration_data,
)
from web.routers.results import (
    router as results_router,
)
from web.routers.settlement import (
    SettlementDependencies,
    auto_check_entries,
    backfill_entry_final_stats,
    classify_default_entry_wagers,
    configure_settlement_router,
    entry_progress,
    grading_report,
    import_final_stats_endpoint,
    pending_entries,
    recheck_entry_final_stats,
    settle_entry,
    settlement_audit,
)
from web.routers.settlement import (
    router as settlement_router,
)
from web.routers.uploads import (
    UploadDependencies,
    analyze_uploaded_file,
    configure_upload_router,
    import_betting_history,
    import_wizard,
)
from web.routers.uploads import router as upload_router
from web.schemas import (
    AiEntryReviewPayload,
    AlertDeliveryPayload,
    AlertDeliveryTestPayload,
    AutoPaperCalibrationPayload,
    BankrollPayload,
    BankrollStrategyPayload,
    BankrollTransactionPayload,
    BetPayload,
    BettingHistoryPayload,
    BoostAnalysisPayload,
    DnpSettingPayload,
    EntryPayload,
    EvPayload,
    FinalStatsPayload,
    HedgeCalculatorPayload,
    LossProtectionSettingPayload,
    MiddleCalculatorPayload,
    ParlayChatPayload,
    ProjectionAssistPayload,
    PropPayload,
    ProviderWeightsPayload,
    RefreshSchedulePayload,
    SettlePayload,
    ShareSlipPayload,
    UploadAnalyzePayload,
    UserPreferencePayload,
    WatchlistItemPayload,
)

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"
STATIC_ASSET_VERSION = "20260824-v250-today-provider-refresh"
ENTRY_DAY_TIME_ZONE = ZoneInfo("America/New_York")
AUDIT_SNAPSHOT_SCHEMA_VERSION = 2
DAILY_BRIEFING_CACHE_VERSION = 12
DAILY_BRIEFING_CACHE_TTL_HOURS = 10
DAILY_SCAN_STATUS_KEY = "daily_briefing_scan_status"
DAILY_SCAN_LOG_KEY = "daily_briefing_run_log"
PROP_FETCH_CACHE_SECONDS = 60
SETTLEMENT_REFRESH_SECONDS = max(900, int(os.getenv("EDGEIQ_SETTLEMENT_REFRESH_SECONDS", "1800")))
SETTLEMENT_INITIAL_REFRESH_SECONDS = max(15, int(os.getenv("EDGEIQ_SETTLEMENT_INITIAL_REFRESH_SECONDS", "30")))
SETTLEMENT_AUTOMATIC_RETRY_HOURS = max(
    6.0,
    float(os.getenv("EDGEIQ_SETTLEMENT_AUTOMATIC_RETRY_HOURS", "24")),
)
COMMAND_CENTER_CACHE_SECONDS = max(30, int(os.getenv("EDGEIQ_COMMAND_CENTER_CACHE_SECONDS", "120")))
OPPORTUNITY_FEED_CACHE_SECONDS = max(30, int(os.getenv("EDGEIQ_OPPORTUNITY_FEED_CACHE_SECONDS", "120")))
BACKTEST_CACHE_SECONDS = max(15, int(os.getenv("EDGEIQ_BACKTEST_CACHE_SECONDS", "30")))
SETTLEMENT_REFRESH_STATUS_KEY = "settlement_refresh_status"
_PROP_FETCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_RESEARCH_PROP_CACHE: dict[str, list[dict]] = {}
_PROP_FETCH_LOCK = threading.RLock()
_PROP_FETCH_KEY_LOCKS: dict[str, threading.Lock] = {}
_PROP_FETCH_METRICS: dict[str, dict[str, int]] = {}
_COMMAND_CENTER_CACHE: dict[tuple, tuple[float, dict]] = {}
_COMMAND_CENTER_LOCK = threading.RLock()
_OPPORTUNITY_FEED_CACHE: dict[tuple, tuple[float, dict]] = {}
_OPPORTUNITY_FEED_LOCK = threading.RLock()
_BACKTEST_CACHE: tuple[float, tuple[object, object], dict] = (0.0, (None, None), {})
_BACKTEST_LOCK = threading.RLock()
_TRENDING_PROPS_CACHE: dict[tuple, tuple[float, dict]] = {}
_TRENDING_PROPS_LOCK = threading.RLock()
_PREDICTION_EVIDENCE_CACHE: tuple[float, list[dict]] = (0.0, [])
_PREDICTION_EVIDENCE_LOCK = threading.RLock()
_MODEL_HEALTH_CACHE: tuple[float, dict] = (0.0, {})
_MODEL_HEALTH_LOCK = threading.RLock()
_SEGMENT_DASHBOARD_CACHE: tuple[float, object | None, dict] = (0.0, None, {})
_SEGMENT_DASHBOARD_LOCK = threading.RLock()
_TRUST_CLV_CACHE: tuple[float, dict] = (0.0, {})
_TRUST_CLV_LOCK = threading.RLock()
_LOSS_PROTECTION_CACHE: tuple[float, tuple[object, ...], dict] = (0.0, (), {})
_LOSS_PROTECTION_LOCK = threading.RLock()
_ENDPOINT_TIMINGS: dict[str, list[dict]] = {}
_ENDPOINT_TIMING_LOCK = threading.RLock()
ENDPOINT_SLOW_THRESHOLD_MS = 1000.0
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
    "CS2",
    "LOL",
    "VALORANT",
    "DOTA2",
    "COD",
    "APEX",
)
ESPORT_SPORTS = frozenset({"CS2", "LOL", "VALORANT", "DOTA2", "COD", "APEX"})
ENTRY_PLATFORMS = ("PrizePicks", "Underdog", "DraftKings Pick6", "Sleeper")
GENERATOR_PLATFORMS = ("PrizePicks", "Underdog", "Sleeper")
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
    "CS": "CS2",
    "CS2": "CS2",
    "COUNTER STRIKE": "CS2",
    "COUNTER-STRIKE": "CS2",
    "LOL": "LOL",
    "LEAGUE OF LEGENDS": "LOL",
    "VAL": "VALORANT",
    "VALORANT": "VALORANT",
    "DOTA": "DOTA2",
    "DOTA2": "DOTA2",
    "DOTA 2": "DOTA2",
    "COD": "COD",
    "CALL OF DUTY": "COD",
    "APEX": "APEX",
    "APEX LEGENDS": "APEX",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    _recover_interrupted_daily_scan()
    settlement_task = asyncio.create_task(_settlement_refresh_loop())
    scheduler_task = asyncio.create_task(_daily_operations_scheduler_loop())
    try:
        yield
    finally:
        settlement_task.cancel()
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await settlement_task
        with suppress(asyncio.CancelledError):
            await scheduler_task


async def _settlement_refresh_loop() -> None:
    """Keep pending entries moving while the local EdgeIQ server is running."""
    await asyncio.sleep(SETTLEMENT_INITIAL_REFRESH_SECONDS)
    while True:
        started_at = utc_now()
        try:
            result = await asyncio.to_thread(
                _auto_check_pending_entries,
                False,
                True,
            )
            status = {
                "ok": True,
                "ran_at": iso_utc(started_at),
                "checked": result.get("checked", 0),
                "settled": result.get("settled", 0),
                "excluded_legacy_paper_entries": result.get("excluded_legacy_paper_entries", 0),
                "imported": result.get("final_stats_refresh", {}).get("imported", 0),
                "message": "Pending entries checked against official final stats.",
            }
        except Exception:
            status = {
                "ok": False,
                "ran_at": iso_utc(started_at),
                "checked": 0,
                "settled": 0,
                "excluded_legacy_paper_entries": 0,
                "imported": 0,
                "message": "The automatic final-stat check could not finish. EdgeIQ will try again.",
            }
        with suppress(Exception):
            SettingsRepository.set(SETTLEMENT_REFRESH_STATUS_KEY, json.dumps(status))
        await asyncio.sleep(SETTLEMENT_REFRESH_SECONDS)


async def _daily_operations_scheduler_loop() -> None:
    """Run configured maintenance jobs once per local schedule window."""
    await asyncio.sleep(20)
    while True:
        try:
            await asyncio.to_thread(_run_due_daily_operations)
        except Exception:
            SettingsRepository.set("daily_scheduler_status", json.dumps({
                "ok": False,
                "ran_at": iso_utc(utc_now()),
                "message": "Scheduled maintenance could not finish. EdgeIQ will retry automatically.",
            }))
        await asyncio.sleep(60)


app = FastAPI(title="EdgeIQ Web", version="2.4.1", lifespan=lifespan)
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


def _normalized_endpoint_path(path: str) -> str:
    normalized = re.sub(r"/(?P<id>\d+)(?=/|$)", "/{id}", path)
    return re.sub(r"(/api/entries/shared/)[^/]+", r"\1{share_id}", normalized)


def _record_endpoint_timing(method: str, path: str, duration_ms: float, status_code: int) -> None:
    if not path.startswith("/api/"):
        return
    key = f"{method.upper()} {_normalized_endpoint_path(path)}"
    sample = {
        "duration_ms": round(max(0.0, float(duration_ms)), 2),
        "status_code": int(status_code),
        "recorded_at": iso_utc(utc_now()),
    }
    with _ENDPOINT_TIMING_LOCK:
        samples = _ENDPOINT_TIMINGS.setdefault(key, [])
        samples.append(sample)
        del samples[:-50]


def _endpoint_timing_snapshot() -> dict:
    with _ENDPOINT_TIMING_LOCK:
        captured = {route: [dict(sample) for sample in samples] for route, samples in _ENDPOINT_TIMINGS.items()}
    routes = []
    for route, samples in captured.items():
        durations = sorted(float(sample["duration_ms"]) for sample in samples)
        if not durations:
            continue
        p95_index = min(len(durations) - 1, max(0, int(round(len(durations) * 0.95)) - 1))
        routes.append({
            "route": route,
            "requests": len(samples),
            "average_ms": round(sum(durations) / len(durations), 1),
            "p95_ms": round(durations[p95_index], 1),
            "max_ms": round(max(durations), 1),
            "failures": sum(1 for sample in samples if int(sample["status_code"]) >= 500),
            "last_status": int(samples[-1]["status_code"]),
            "last_recorded_at": samples[-1]["recorded_at"],
            "slow": max(durations) >= ENDPOINT_SLOW_THRESHOLD_MS,
        })
    routes.sort(key=lambda row: (row["slow"], row["p95_ms"], row["max_ms"]), reverse=True)
    return {
        "requests": sum(row["requests"] for row in routes),
        "slow_requests": sum(
            1
            for samples in captured.values()
            for sample in samples
            if float(sample["duration_ms"]) >= ENDPOINT_SLOW_THRESHOLD_MS
        ),
        "slow_threshold_ms": int(ENDPOINT_SLOW_THRESHOLD_MS),
        "routes": routes[:20],
    }


@app.middleware("http")
async def record_endpoint_performance(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000.0
        _record_endpoint_timing(request.method, request.url.path, duration_ms, status_code)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


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


def _clv_report_payload() -> dict:
    stored_entries = EntryRepository.all()
    histories = LineHistoryRepository.get_histories([
        prop
        for entry in stored_entries
        for prop in entry.get("props", [])
        if prop.get("player") and prop.get("stat") and prop.get("platform")
    ])
    entries = [_entry_clv_payload(entry, histories) for entry in stored_entries]
    tracked = [entry for entry in entries if entry["legs"]]
    clv_values = [leg["clv"] for entry in tracked for leg in entry["legs"] if leg["clv"] is not None]
    quarantined = [leg for entry in tracked for leg in entry["legs"] if leg.get("clv") is None]
    positive = sum(1 for value in clv_values if value > 0)
    return {
        "entries": tracked,
        "average_clv": round(sum(clv_values) / len(clv_values), 2) if clv_values else 0.0,
        "positive_clv_rate": round((positive / len(clv_values) * 100), 1) if clv_values else 0.0,
        "tracked_legs": len(clv_values),
        "quarantined_legs": len(quarantined),
        "quarantine_reasons": _count_values(leg.get("reliability_reason", "unverified") for leg in quarantined),
    }


def _portfolio_intelligence_payload() -> dict:
    pending = EntryRepository.pending()
    histories = LineHistoryRepository.get_histories([
        prop
        for entry in pending
        for prop in entry.get("props", [])
        if prop.get("player") and prop.get("stat") and prop.get("platform")
    ])
    checked_at = utc_now()
    market_entries = [_entry_live_market_payload(entry, histories, now=checked_at) for entry in pending]
    intelligence = build_portfolio_intelligence_payload(
        pending_entries=pending,
        bankroll=float(get_dashboard().get("bankroll") or get_starting_bankroll() or 0.0),
        strategy=_bankroll_strategy(),
    )
    intelligence["monitor"] = build_active_portfolio_monitor_payload(
        pending_entries=pending,
        market_entries=market_entries,
        now=checked_at,
    )
    return intelligence


def _refresh_portfolio_market_data_payload() -> dict:
    return build_refresh_portfolio_market_payload(
        pending_entries=EntryRepository.pending(),
        fetch_platform_props=lambda platform, **kwargs: _fetch_platform_props(platform, **kwargs),
        intelligence=lambda: _portfolio_intelligence_payload(),
    )


def _unknown_entry_leg_count(entries: list[dict]) -> int:
    unknown = 0
    for entry in entries:
        if entry.get("status") not in {"Pending", "Settled", "Excluded"}:
            continue
        for prop in entry.get("props", []):
            result = str(prop.get("final_result") or prop.get("result") or "").strip()
            final_status = str(prop.get("final_status") or "").strip().lower()
            final_source = str(prop.get("final_source") or "").strip().lower()
            actual = prop.get("actual")
            if final_source == "projection_estimate" or final_status == "estimated":
                unknown += 1
                continue
            if result in {"Win", "Loss", "Push", "DNP"} or final_status in {"played", "dnp"} or actual is not None:
                continue
            unknown += 1
    return unknown


def _entries_needing_final_stat_refresh(entries: list[dict]) -> list[dict]:
    refresh_entries = []
    for entry in entries:
        props = []
        for prop in entry.get("props", []):
            if not _supports_automatic_final_stat(prop):
                continue
            final_source = str(prop.get("final_source") or "").strip().lower()
            final_status = str(prop.get("final_status") or "").strip().lower()
            needs_refresh = (
                entry.get("status") == "Pending"
                or prop.get("actual") is None
                or final_source in {"", "unmatched", "projection_estimate", "actual_provider"}
                or final_status not in {"played", "dnp"}
            )
            if needs_refresh:
                props.append(prop)
        if props:
            refresh_entries.append({**entry, "props": props})
    return refresh_entries


def _auto_check_pending_entries(allow_estimates: bool = False, refresh_providers: bool = True) -> dict:
    reopened = _reopen_recent_partial_settlements()
    pending_entries = EntryRepository.pending()
    excluded = _exclude_stale_unverifiable_paper_entries(pending_entries)
    if excluded:
        pending_entries = EntryRepository.pending()
    game_time_recovery = (
        _backfill_missing_game_times(pending_entries)
        if pending_entries and refresh_providers
        else {"provider": "espn", "skipped": True, "updated": 0, "fetched_rows": 0, "errors": []}
    )
    if game_time_recovery.get("updated"):
        pending_entries = EntryRepository.pending()
    refresh_entries = _entries_due_for_automatic_final_refresh(pending_entries)
    refresh = (
        _refresh_final_stats(refresh_entries)
        if refresh_entries and refresh_providers
        else {"provider": "local_cache", "skipped": True, "imported": 0, "errors": []}
    )
    refresh["eligible_entries"] = len(refresh_entries)
    refresh["deferred_entries"] = max(0, len(pending_entries) - len(refresh_entries))
    checks = [_check_entry_result(entry, allow_estimates) for entry in pending_entries]
    settled = [check for check in checks if check["settled"]]
    excluded_expired = _exclude_expired_unresolved_paper_entries(EntryRepository.pending())
    return {
        "checked": len(checks),
        "settled": len(settled),
        "entries": checks,
        "estimated": any(check["source"] == "projection_estimate" for check in checks),
        "final_stats_refresh": refresh,
        "excluded_legacy_paper_entries": excluded,
        "excluded_expired_paper_entries": excluded_expired,
        "reopened_partial_settlements": reopened,
        "game_time_recovery": game_time_recovery,
    }


def _entries_due_for_automatic_final_refresh(
    entries: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    current = (now or utc_now()).replace(tzinfo=UTC)
    due_entries = []
    for entry in entries:
        props = [
            prop
            for prop in entry.get("props", [])
            if _prop_due_for_automatic_final_refresh(prop, current)
        ]
        if props:
            due_entries.append({**entry, "props": props})
    return due_entries


def _prop_due_for_automatic_final_refresh(prop: dict, now: datetime) -> bool:
    if not _supports_automatic_final_stat(prop):
        return False
    if prop.get("actual") is not None or str(prop.get("final_status") or "").lower() in {"played", "dnp"}:
        return False
    start = _parse_game_time(prop.get("game_time", ""))
    if start is None:
        return False
    age = now - start
    return (
        age >= timedelta(hours=_sport_final_pending_hours(prop.get("sport", "")))
        and age < timedelta(hours=SETTLEMENT_AUTOMATIC_RETRY_HOURS)
    )


def _automatic_final_retry_expired(prop: dict, now: datetime | None = None) -> bool:
    start = _parse_game_time(prop.get("game_time", ""))
    if start is None:
        return False
    current = (now or utc_now()).replace(tzinfo=UTC)
    return current - start >= timedelta(hours=SETTLEMENT_AUTOMATIC_RETRY_HOURS)


def _reopen_recent_partial_settlements(max_age_hours: float = 72.0) -> list[int]:
    now = utc_now().replace(tzinfo=UTC)
    reopened: list[int] = []
    for entry in EntryRepository.all():
        if entry.get("status") != "Settled" or entry.get("result") != "Loss":
            continue
        props = entry.get("props") or []
        has_final_loss = any(
            str(prop.get("final_result") or prop.get("result") or "") == "Loss"
            and str(prop.get("final_status") or "").strip().lower() == "played"
            for prop in props
        )
        has_unresolved = any(
            prop.get("actual") is None
            or str(prop.get("final_status") or "").strip().lower() not in {"played", "dnp"}
            for prop in props
        )
        if not has_final_loss or not has_unresolved:
            continue
        reference = _latest_entry_game_time(entry) or _aware_datetime_value(entry.get("settled_at"))
        if reference is None or now - reference > timedelta(hours=max_age_hours):
            continue
        EntryRepository.reopen_for_settlement(
            int(entry["id"]),
            "A loss was recorded before every leg had confirmed final status.",
        )
        reopened.append(int(entry["id"]))
    return reopened


def _latest_entry_game_time(entry: dict) -> datetime | None:
    starts = [
        parsed
        for parsed in (_parse_game_time(prop.get("game_time", "")) for prop in entry.get("props", []))
        if parsed is not None
    ]
    return max(starts) if starts else None


def _exclude_stale_unverifiable_paper_entries(entries: list[dict]) -> int:
    now = utc_now().replace(tzinfo=UTC)
    excluded = 0
    for entry in entries:
        if str(entry.get("entry_mode") or "real").lower() != "paper":
            continue
        props = entry.get("props", [])
        unsupported = [prop for prop in props if not _end_to_end_prop_eligibility(prop)["eligible"]]
        if not unsupported or not _legacy_entry_is_past_due(entry, now):
            continue
        reason = "Saved before end-to-end final-stat verification; excluded from calibration because an official grading path is unavailable."
        EntryRepository.exclude_from_tracking(int(entry["id"]), reason)
        excluded += 1
    return excluded


def _exclude_expired_unresolved_paper_entries(entries: list[dict]) -> int:
    excluded = 0
    for entry in entries:
        if str(entry.get("entry_mode") or "real").lower() != "paper":
            continue
        unresolved = [
            prop
            for prop in entry.get("props", [])
            if prop.get("actual") is None
            and str(prop.get("final_status") or "").strip().lower() not in {"played", "dnp"}
        ]
        if not unresolved or not all(_automatic_final_retry_expired(prop) for prop in unresolved):
            continue
        EntryRepository.exclude_from_tracking(
            int(entry["id"]),
            "Official final stats remained unavailable after the retry window; excluded from calibration instead of assigning a result.",
        )
        excluded += 1
    return excluded


def _quarantine_mismatched_settlement_evidence() -> dict:
    mismatches = SettlementAuditRepository.game_date_mismatches()
    quarantined = PredictionLedgerRepository.quarantine_entry_props(
        [row["entry_prop_id"] for row in mismatches]
    )
    return {
        "detected": len(mismatches),
        "quarantined": quarantined,
        "entries": len({row["entry_id"] for row in mismatches}),
        "items": mismatches,
        "message": (
            f"Excluded {quarantined} prediction records with conflicting game dates from model calibration."
            if quarantined
            else "No new conflicting game-date evidence was added to calibration."
        ),
    }


def _legacy_entry_is_past_due(entry: dict, now: datetime) -> bool:
    starts = [
        start for start in (_parse_game_time(prop.get("game_time", "")) for prop in entry.get("props", []))
        if start is not None
    ]
    if starts:
        latest_start = max(starts)
        max_hours = max(
            (_sport_final_pending_hours(prop.get("sport", "")) for prop in entry.get("props", [])),
            default=4.5,
        )
        return now >= latest_start + timedelta(hours=max_hours)

    placed_at = entry.get("placed_at")
    if isinstance(placed_at, str):
        try:
            placed_at = datetime.fromisoformat(placed_at.replace("Z", "+00:00"))
        except ValueError:
            placed_at = None
    if not isinstance(placed_at, datetime):
        return False
    if placed_at.tzinfo is None:
        placed_at = placed_at.replace(tzinfo=UTC)
    return now >= placed_at.astimezone(UTC) + timedelta(hours=24)


def _recheck_entry_results(entries: list[dict], allow_estimates: bool = False) -> dict:
    reviewed = []
    corrected = 0
    settled = 0
    for entry in entries:
        if entry.get("status") not in {"Pending", "Settled", "Excluded"}:
            continue
        evaluation = _evaluate_entry_result(entry, allow_estimates)
        if not evaluation["settled"]:
            reviewed.append({
                "id": entry.get("id"),
                "previous_result": entry.get("result") or "",
                "new_result": "Unknown",
                "changed": False,
                "settled": False,
                "message": evaluation["message"],
            })
            continue
        previous = entry.get("result") or ""
        if entry.get("status") in {"Pending", "Excluded"}:
            settled += 1
        stored = EntryRepository.settle(
            entry["id"],
            evaluation["result"],
            dnp_legs=evaluation["dnp_legs"],
            dnp_mode=_dnp_mode(),
            leg_results=evaluation["legs"],
        )
        stored_result = stored.get("result", evaluation["result"]) if isinstance(stored, dict) else evaluation["result"]
        changed = previous != stored_result
        if changed:
            corrected += 1
        if stored_result != evaluation["result"]:
            message = "DNP handling adjusted the final entry result."
        else:
            message = evaluation["message"]
        reviewed.append({
            "id": entry.get("id"),
            "previous_result": previous,
            "new_result": stored_result,
            "changed": changed,
            "settled": True,
            "message": message,
        })
    return {
        "reviewed": len(reviewed),
        "corrected": corrected,
        "settled": settled,
        "entries": reviewed,
    }


def _entry_leg_final_snapshots(entry: dict, allow_estimates: bool) -> list[dict]:
    legs = []
    for prop in entry.get("props", []):
        final_stat = _confirmed_final_stat_for_entry(prop, entry)
        actual = final_stat.get("actual") if final_stat else None
        status = str(final_stat.get("status") if final_stat else "").strip().lower()
        source = str(final_stat.get("source") if final_stat else "").strip() or "unmatched"
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
        _record_settlement_audit(entry, prop, final_stat, actual, result, source, final_status)
        legs.append({**prop, "actual": actual, "result": result, "source": source, "final_status": final_status})
    return legs


def _record_settlement_audit(
    entry: dict,
    prop: dict,
    final_stat: dict | None,
    actual: float | None,
    result: str,
    source: str,
    final_status: str,
) -> None:
    eligible = _supports_automatic_final_stat(prop)
    provider_plan = _settlement_provider_plan(prop)
    if actual is not None or final_status == "dnp":
        status = "verified"
        reason_code = "final_stat_matched"
        message = f"Final result verified from {source}."
    elif _game_has_not_started(prop):
        status = "scheduled"
        reason_code = "game_not_started"
        message = "The game has not started. Final-stat checks will begin after the expected completion window."
    elif eligible and _automatic_final_retry_expired(prop):
        status = "blocked"
        reason_code = "official_final_retry_window_expired"
        message = (
            f"No verified final appeared within {SETTLEMENT_AUTOMATIC_RETRY_HOURS:g} hours of game time. Automatic retries stopped "
            "to protect provider limits; this leg is excluded from calibration until verified."
        )
    elif eligible:
        status = "waiting"
        reason_code = "official_final_not_available"
        message = "The official final box score has not produced a matching stat yet; EdgeIQ will retry automatically."
    else:
        status = "blocked"
        reason_code = "unsupported_settlement_path"
        message = "This legacy market does not have a supported automatic final-stat path."
    with suppress(Exception):
        SettlementAuditRepository.record({
            "entry_id": entry.get("id"),
            "entry_prop_id": prop.get("entry_prop_id"),
            "status": status,
            "provider": source if source != "unmatched" else (provider_plan[0] if provider_plan else "Provider pending"),
            "matched_identity_id": (final_stat or {}).get("player_identity_id"),
            "requested_player": prop.get("player"),
            "matched_player": (final_stat or {}).get("player", ""),
            "requested_game": prop.get("game"),
            "matched_game": (final_stat or {}).get("game", ""),
            "actual": actual,
            "result": result,
            "reason_code": reason_code,
            "message": message,
            "details": {
                "stat": prop.get("stat", ""),
                "line": prop.get("line"),
                "direction": prop.get("direction", "Over"),
                "final_status": final_status,
                "provider_plan": provider_plan,
                "sport": prop.get("sport", ""),
                "game_time": prop.get("game_time", ""),
            },
        })


def _settlement_provider_plan(prop: dict) -> list[str]:
    sport = str(prop.get("sport") or "").upper()
    if sport in ESPORT_SPORTS:
        return ["PandaScore"] if sport in pandascore.supported_sports() else []
    providers = ["ESPN official box score"]
    if sport == "NBA":
        providers.append("NBA Stats Summer League")
    if sport in {"NBA", "NFL", "NHL"} and os.getenv("SPORTSDATAIO_API_KEY", "").strip():
        providers.append("SportsDataIO cross-check")
    return providers


def _game_has_not_started(prop: dict, now: datetime | None = None) -> bool:
    start = _parse_game_time(prop.get("game_time", ""))
    if start is None:
        return False
    current = (now or utc_now()).replace(tzinfo=UTC)
    return current < start


def _performance_payload() -> dict:
    return build_performance_payload()


def _backtest_payload() -> dict:
    global _BACKTEST_CACHE
    now = time.monotonic()
    source_key = (EntryRepository.all, BetRepository.get_all)
    with _BACKTEST_LOCK:
        expires_at, cached_source_key, cached = _BACKTEST_CACHE
        if cached and cached_source_key == source_key and expires_at > now:
            return {**cached, "cache": {"hit": True, "ttl_seconds": BACKTEST_CACHE_SECONDS}}
    payload = build_backtest_payload(clv_report())
    with _BACKTEST_LOCK:
        _BACKTEST_CACHE = (now + BACKTEST_CACHE_SECONDS, source_key, payload)
    return {**payload, "cache": {"hit": False, "ttl_seconds": BACKTEST_CACHE_SECONDS}}


def _data_integrity_repair_payload(dry_run: bool = True) -> dict:
    before = _backtest_payload()
    backup = None
    if not dry_run:
        backup = backup_database()
    repair = EntryRepository.quarantine_implausible_markets(dry_run=dry_run)
    incomplete = PredictionLedgerRepository.quarantine_incomplete_settled(dry_run=dry_run)
    after = _backtest_payload() if not dry_run else before
    return {
        **repair,
        "incomplete_settled_predictions": incomplete,
        "backup": backup,
        "metrics_before": {
            "scorecard": before.get("scorecard", {}),
            "tracked": before.get("tracked", {}),
            "calibration": before.get("calibration", []),
        },
        "metrics_after": {
            "scorecard": after.get("scorecard", {}),
            "tracked": after.get("tracked", {}),
            "calibration": after.get("calibration", []),
        },
        "message": (
            f"Preview found {repair['candidate_entries']} entries with invalid markets and "
            f"{incomplete['candidates']} settled predictions without verified leg results. No records changed."
            if dry_run
            else f"Quarantined {repair['quarantined_entries']} invalid entries and "
            f"{incomplete['quarantined']} incomplete settled predictions, then rebuilt model metrics."
        ),
    }


def _refresh_calibration_data_payload() -> dict:
    entries = EntryRepository.all()
    refresh_entries = [
        {**entry, "props": [prop for prop in entry.get("props", []) if not _game_has_not_started(prop)]}
        for entry in _entries_needing_final_stat_refresh(entries)
    ]
    refresh_entries = [entry for entry in refresh_entries if entry["props"]]
    provider_refresh = _refresh_final_stats(refresh_entries)
    refreshed_ids = {int(entry.get("id") or 0) for entry in refresh_entries}
    unresolved_settled_ids = {
        int(entry.get("id") or 0)
        for entry in entries
        if entry.get("status") == "Settled"
        and any(
            prop.get("actual") is None
            or prop.get("final_result") not in {"Win", "Loss", "Push", "DNP"}
            for prop in entry.get("props", [])
        )
    }
    backfill_ids = refreshed_ids | unresolved_settled_ids
    latest_targets = [entry for entry in EntryRepository.all() if int(entry.get("id") or 0) in backfill_ids]
    backfill = _backfill_settled_entry_leg_results(latest_targets)
    board_settlement = BoardOfferRepository.settle_pending(limit=1000)
    return {
        "entries_targeted": len(refresh_entries),
        "provider_refresh": provider_refresh,
        "backfill": backfill,
        "board_settlement": board_settlement,
        "backtest": backtest_summary(BetRepository().get_all(), EntryRepository.all()),
    }


def _import_betting_history_payload(payload: str, source: str) -> dict:
    return build_import_betting_history_payload(payload, source)


def _fetch_props(platform: str, sport_filter: str | None) -> list[dict]:
    selected = _selected_platforms(platform)
    if sport_filter in ESPORT_SPORTS:
        # Gaming markets are captured for research, but remain outside the
        # paid recommendation feed until a verified result source is wired.
        if len(selected) > 1:
            with ThreadPoolExecutor(max_workers=len(selected)) as pool:
                list(pool.map(_fetch_platform_props, selected))
        elif selected:
            _fetch_platform_props(selected[0])
        with _PROP_FETCH_LOCK:
            props = [
                dict(prop)
                for platform_name in selected
                for prop in _RESEARCH_PROP_CACHE.get(_canonical_platform(platform_name), [])
                if str(prop.get("league") or prop.get("sport") or "").upper() == sport_filter
            ]
    elif len(selected) > 1:
        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            batches = list(pool.map(_fetch_platform_props, selected))
        props = [prop for batch in batches for prop in batch]
    else:
        props = _fetch_platform_props(selected[0]) if selected else []

    if sport_filter:
        props = [prop for prop in props if prop.get("league", "").upper() == sport_filter]
    rows = [dict(prop) for prop in props]
    snapshot_rows = sorted(
        rows,
        key=lambda row: int(row.get("trending_count") or 0),
        reverse=True,
    )[:500]
    ModelRehabilitationRepository.save_feed({
        "feed": {
            "id": "edgeiq-recommendation-snapshot-v2.2",
            "canonical": True,
            "platform": platform,
            "sport": sport_filter or "All Sports",
            "captured_at": iso_utc(utc_now()),
            "available_count": len(rows),
            "stored_count": len(snapshot_rows),
        },
        "props": snapshot_rows,
    })
    return rows


def _cached_props(platform: str, sport_filter: str | None) -> list[dict]:
    """Return already-loaded provider offers without starting network work."""
    rows: list[dict] = []
    with _PROP_FETCH_LOCK:
        for platform_name in _selected_platforms(platform):
            canonical = _canonical_platform(platform_name)
            cache_key = f"{canonical}:{_platform_fetcher_cache_token(canonical)}"
            cached = _PROP_FETCH_CACHE.get(cache_key)
            if cached:
                rows.extend(dict(prop) for prop in cached[1])
    if sport_filter:
        rows = [
            row for row in rows
            if str(row.get("league") or row.get("sport") or "").upper() == sport_filter
        ]
    return rows


def _fetch_platform_props(platform: str, *, force_refresh: bool = False) -> list[dict]:
    canonical = _canonical_platform(platform)
    fetcher = _platform_prop_fetcher(canonical)
    if fetcher is None:
        return []
    cache_key = f"{canonical}:{_platform_fetcher_cache_token(canonical)}"
    now = time.monotonic()
    with _PROP_FETCH_LOCK:
        cached = _PROP_FETCH_CACHE.get(cache_key)
        if not force_refresh and cached and cached[0] > now:
            _increment_prop_fetch_metric(canonical, "memory_cache_hits")
            return [dict(prop) for prop in cached[1]]
        key_lock = _PROP_FETCH_KEY_LOCKS.setdefault(cache_key, threading.Lock())

    with key_lock:
        now = time.monotonic()
        with _PROP_FETCH_LOCK:
            cached = _PROP_FETCH_CACHE.get(cache_key)
            if not force_refresh and cached and cached[0] > now:
                _increment_prop_fetch_metric(canonical, "coalesced_hits")
                return [dict(prop) for prop in cached[1]]
        props = _fetch_platform_props_uncached(canonical, fetcher)
        with _PROP_FETCH_LOCK:
            _increment_prop_fetch_metric(canonical, "provider_fetches")
            _PROP_FETCH_CACHE[cache_key] = (now + PROP_FETCH_CACHE_SECONDS, [dict(prop) for prop in props])
        _record_line_snapshots(props, force_snapshot=force_refresh)
        return [dict(prop) for prop in props]


def _increment_prop_fetch_metric(platform: str, metric: str) -> None:
    values = _PROP_FETCH_METRICS.setdefault(platform, {})
    values[metric] = values.get(metric, 0) + 1


def _platform_prop_fetcher(platform: str):
    canonical = _canonical_platform(platform)
    providers = {
        "PrizePicks": _fetch_prizepicks_platform_props,
        "Underdog": underdog.fetch_projections,
        "Sleeper": sleeper.fetch_projections,
        "Ball Don't Lie": _fetch_balldontlie_platform_props,
    }
    return providers.get(canonical)


def _fetch_prizepicks_platform_props() -> list[dict]:
    return prizepicks.fetch_projections(limit=1000)


def _fetch_balldontlie_platform_props() -> list[dict]:
    return balldontlie.fetch_props()


def _platform_fetcher_cache_token(platform: str) -> int:
    canonical = _canonical_platform(platform)
    def token(func) -> int:
        code = getattr(func, "__code__", None)
        return hash((id(func), getattr(code, "co_filename", ""), getattr(code, "co_firstlineno", 0)))

    tokens = {
        "PrizePicks": token(prizepicks.fetch_projections),
        "Underdog": token(underdog.fetch_projections),
        "Sleeper": token(sleeper.fetch_projections),
        "Ball Don't Lie": token(balldontlie.fetch_props),
    }
    return tokens.get(canonical, 0)


def _fetch_platform_props_uncached(platform: str, fetcher) -> list[dict]:
    canonical = _canonical_platform(platform)
    attempted_at = iso_utc(utc_now())
    try:
        props = fetcher()
    except Exception as exc:
        _record_provider_fetch_status(canonical, attempted_at, error=str(exc))
        return []
    for prop in props:
        prop.setdefault("platform", canonical)
        eligibility = _end_to_end_prop_eligibility(prop)
        prop["end_to_end_confirmed"] = bool(eligibility["eligible"])
        prop["eligibility_reason"] = "; ".join(eligibility.get("reasons") or [])
    # Capture the provider's complete board before recommendation and
    # settlement filters introduce selection bias.
    with suppress(Exception):
        BoardOfferRepository.record_many(props, canonical)
    actionable = [
        prop for prop in props
        if _is_actionable_provider_prop(prop)
    ]
    if canonical == "PrizePicks":
        actionable = _enrich_prizepicks_adjusted_lines(actionable)
    research_rows = []
    for prop in actionable:
        if str(prop.get("league") or prop.get("sport") or "").upper() not in ESPORT_SPORTS:
            continue
        eligibility = _end_to_end_prop_eligibility(prop)
        confirmed = bool(eligibility["eligible"])
        research_rows.append({
            **prop,
            "research_only": not confirmed,
            "end_to_end_confirmed": confirmed,
            "forecast_paid_eligible": confirmed,
            "settlement_provider": eligibility.get("provider") or "PandaScore access needed",
            "settlement_reason": (eligibility.get("reasons") or [""])[0],
            "data_strength": (
                ["Provider-backed", "Final stats verified path"]
                if confirmed
                else ["Provider-backed", "Final stats unavailable"]
            ),
        })
    with _PROP_FETCH_LOCK:
        _RESEARCH_PROP_CACHE[canonical] = research_rows
    eligible = [prop for prop in actionable if _end_to_end_prop_eligibility(prop)["eligible"]]
    _record_provider_fetch_status(canonical, attempted_at, row_count=len(eligible))
    return eligible


def _record_provider_fetch_status(platform: str, attempted_at: str, row_count: int = 0, error: str = "") -> None:
    key = _provider_status_key(platform)
    previous = _safe_json_loads(SettingsRepository.get(key, ""))
    payload = {
        "last_attempt_at": attempted_at,
        "last_success_at": previous.get("last_success_at", "") if error else attempted_at,
        "last_error_at": attempted_at if error else previous.get("last_error_at", ""),
        "last_error": error,
        "row_count": int(row_count if not error else previous.get("row_count", 0) or 0),
    }
    with suppress(Exception):
        SettingsRepository.set(key, json.dumps(payload))


def _enrich_prizepicks_adjusted_lines(props: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for prop in props:
        groups.setdefault(_prizepicks_offer_group_key(prop), []).append(prop)

    enriched: list[dict] = []
    for group in groups.values():
        standard_lines = [
            float(prop["line"])
            for prop in group
            if prop.get("line") is not None and _prizepicks_offer_type(prop) == "standard"
        ]
        standard_line = _median_line(standard_lines) if standard_lines else None
        for prop in group:
            row = dict(prop)
            if standard_line is not None:
                row["standard_line"] = standard_line
            offer_type = _prizepicks_offer_type(row)
            if standard_line is not None:
                row["baseline_line"] = standard_line
            else:
                row["baseline_line"] = float(row.get("line") or 0.0)
            row["line_offer_type"] = offer_type
            row["adjusted_line"] = offer_type != "standard"
            row["is_discounted_line"] = offer_type == "goblin"
            row["is_premium_line"] = offer_type == "demon"
            if offer_type == "demon":
                row["direction"] = "Over"
                row["allowed_directions"] = ["Over"]
            if row["adjusted_line"] and standard_line is not None:
                row["line_discount"] = round(standard_line - float(row.get("line") or standard_line), 2)
            else:
                row["line_discount"] = 0.0
            enriched.append(row)
    return enriched


def _prizepicks_offer_group_key(prop: dict) -> tuple[str, str, str, str, str]:
    player_key = str(prop.get("player_id") or canonical_person_key(prop.get("player")))
    return (
        player_key,
        str(prop.get("stat") or "").strip().lower(),
        str(prop.get("league") or "").strip().upper(),
        canonical_matchup_key(prop.get("game"), EntryRepository.TEAM_ALIASES),
        str(prop.get("team") or "").strip().upper(),
    )


def _prizepicks_offer_type(prop: dict) -> str:
    odds_type = str(prop.get("odds_type") or "").strip().lower()
    if odds_type in {"standard", "goblin", "demon"}:
        return odds_type
    if prop.get("adjusted_odds"):
        line = float(prop.get("line") or 0.0)
        standard_line = float(prop.get("standard_line") or line)
        if line < standard_line:
            return "goblin"
        if line > standard_line:
            return "demon"
        return "adjusted"
    return "standard"


def _median_line(lines: list[float]) -> float:
    ordered = sorted(lines)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def _is_actionable_provider_prop(prop: dict) -> bool:
    player = str(prop.get("player") or "").strip()
    line = prop.get("line")
    if not player or player.lower() == "unknown" or line is None:
        return False
    return (
        not is_combined_player_prop(prop)
        and not is_partial_game_market(prop.get("stat"))
        and not _is_season_long_prop(prop)
        and prop_line_plausibility(prop).valid
    )


def _end_to_end_prop_eligibility(prop: dict | PropPayload, *, require_context: bool = True) -> dict:
    """Return whether a provider prop has a verified end-to-end settlement path."""
    sport = str(_prop_value(prop, "sport") or _prop_value(prop, "league") or "").strip().upper()
    raw_stat = str(_prop_value(prop, "stat") or "").strip().lower()
    stat = _settlement_stat_key(_prop_value(prop, "stat"))
    position = str(_prop_value(prop, "position") or "").strip().lower()
    player = str(_prop_value(prop, "player") or "").strip()
    team = str(_prop_value(prop, "team") or "").strip()
    game = str(_prop_value(prop, "game") or "").strip()
    game_time = str(_prop_value(prop, "game_time") or "").strip()
    reasons: list[str] = []
    plausibility = prop_line_plausibility(prop)

    basketball_stats = {
        "points", "rebounds", "assists", "steals", "blocks", "turnovers",
        "3 pointers made", "pra", "points rebounds assists", "points rebounds",
        "points assists", "rebounds assists", "steals blocks", "3 pointers attempted",
        "field goals made", "field goals attempted", "free throws made", "free throws attempted",
        "2 pointers made", "2 pointers attempted", "offensive rebounds", "defensive rebounds",
        "double doubles", "triple doubles", "fantasy score",
    }
    baseball_hitting_stats = {
        "at bats", "plate appearances", "hits", "runs", "rbis", "home runs",
        "hits runs rbis", "total bases", "singles", "doubles", "triples", "walks",
        "stolen bases", "hit by pitch", "strikeouts",
    }
    baseball_pitching_stats = {
        "points", "fantasy score", "pitcher fantasy score", "pitcher strikeouts", "strikeouts",
        "pitching outs", "outs recorded", "earned runs", "hits allowed", "pitching walks",
        "pitches", "batters faced",
    }
    football_stats = {
        "pass yards", "passing yards", "pass tds", "passing tds", "completions",
        "pass completions", "passing attempts", "pass attempts", "int", "ints thrown",
        "interceptions", "interceptions thrown", "defensive interceptions", "rush yards", "rushing yards",
        "rush attempts", "carries", "rush tds", "rushing tds", "rec yards",
        "receiving yards", "receptions", "targets", "rec tds", "receiving tds",
        "rush rec yards", "rush rec tds", "sacks", "xp made", "extra points made",
        "extra points attempted", "field goals made", "field goals attempted",
        "kicking field goals made", "kicking field goals attempted", "longest field goal",
        "pass rush yards", "pass rush tds", "kicking points", "tackles", "solo tackles",
        "assisted tackles",
    }
    pitcher_positions = {"p", "sp", "rp", "pitcher", "starting pitcher", "relief pitcher"}

    settlement_provider = ""
    market_supported = False
    if sport in ESPORT_SPORTS:
        esports_support = pandascore.market_support(sport, _prop_value(prop, "stat"))
        market_supported = bool(esports_support["eligible"])
        settlement_provider = str(esports_support["provider"])
        reasons.extend(esports_support["reasons"])
    elif is_partial_game_market(raw_stat):
        market_supported = False
    elif sport in {"NBA", "WNBA"}:
        market_supported = stat in basketball_stats
    elif sport == "MLB":
        if stat in baseball_hitting_stats:
            market_supported = True
        elif stat in baseball_pitching_stats:
            market_supported = (
                stat not in {"points", "fantasy score", "strikeouts"}
                or "pitcher" in raw_stat
                or position in pitcher_positions
            )
    elif sport == "NFL":
        market_supported = stat in football_stats
        if any(label in raw_stat for label in ("first td", "first touchdown", "fantasy point")):
            market_supported = False
    elif sport == "NHL":
        market_supported = stat in {
            "goals", "assists", "points", "shots on goal", "blocked shots", "hits",
            "saves", "goalie saves", "goals against", "shots against",
        }

    platform = str(_prop_value(prop, "platform") or "").strip().lower()
    if stat == "fantasy score" and platform in {"draftkings", "draftkings pick6", "dk pick6"}:
        market_supported = False
        reasons.append("DraftKings fantasy scoring requires a provider-specific formula snapshot")

    if not player or player.lower() == "unknown":
        reasons.append("named player is required")
    if _prop_value(prop, "line") is not None and not plausibility.valid:
        reasons.append(plausibility.reason)
    if not market_supported and sport not in ESPORT_SPORTS:
        reasons.append(f"official final-stat coverage is unavailable for {sport or 'this sport'} {str(_prop_value(prop, 'stat') or 'market')}")
    if require_context:
        if not game:
            reasons.append("matchup is missing")
        elif not re.search(r"\S+\s*(?:@|\bvs\.?\b|\bversus\b)\s*\S+", game, flags=re.IGNORECASE):
            team_key = re.sub(r"[^A-Z0-9]", "", team.upper())
            opponent_key = re.sub(r"[^A-Z0-9]", "", game.upper())
            if not team_key or not opponent_key or team_key == opponent_key:
                reasons.append("full two-team matchup is missing")
        if not game_time or _parse_game_time(game_time) is None:
            reasons.append("confirmed game time is missing")

    return {
        "eligible": not reasons,
        "sport": sport,
        "stat": stat,
        "provider": settlement_provider or ("ESPN official box score" if market_supported else ""),
        "reasons": reasons,
        "plausibility": plausibility.as_dict(),
    }


def _settlement_stat_key(value: object) -> str:
    canonical = canonical_stat_label(value)
    key = re.sub(r"[^a-z0-9]+", " ", str(canonical or value or "").strip().lower()).strip()
    aliases = {
        "pts rebs asts": "points rebounds assists",
        "pts reb ast": "points rebounds assists",
        "points rebs asts": "points rebounds assists",
        "pts rebs": "points rebounds",
        "pts asts": "points assists",
        "rebs asts": "rebounds assists",
        "stls blks": "steals blocks",
    }
    return aliases.get(key, key)


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
        return list(GENERATOR_PLATFORMS)
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
    if normalized in {"draftkings", "draft kings", "draftkings pick6", "dk pick6", "pick6"}:
        return "DraftKings Pick6"
    for platform in PROP_PLATFORMS:
        if platform.lower() == normalized:
            return platform
    return "PrizePicks"


def _refresh_final_stats(pending_entries: list[dict]) -> dict:
    espn_refresh = refresh_final_stats_for_entries(pending_entries)
    sportsdataio_refresh = _sportsdataio_refresh(pending_entries)
    summer_league_refresh = nba_summer_league.refresh_final_stats_for_entries(pending_entries)
    pandascore_refresh = pandascore.refresh_final_stats_for_entries(pending_entries)
    if not pandascore_refresh.get("skipped"):
        _record_provider_fetch_status(
            "PandaScore",
            iso_utc(utc_now()),
            row_count=int(pandascore_refresh.get("fetched_rows") or 0),
            error="; ".join(pandascore_refresh.get("errors") or []),
        )
    imported = (
        espn_refresh.get("imported", 0)
        + sportsdataio_refresh.get("imported", 0)
        + summer_league_refresh.get("imported", 0)
        + pandascore_refresh.get("imported", 0)
    )
    fetched_rows = (
        espn_refresh.get("fetched_rows", 0)
        + sportsdataio_refresh.get("fetched_rows", 0)
        + summer_league_refresh.get("fetched_rows", 0)
        + pandascore_refresh.get("fetched_rows", 0)
    )
    return {
        "providers": ["espn", "sportsdataio", "nba_summer_league", "pandascore"],
        "provider": "espn+sportsdataio+nba_summer_league+pandascore",
        "espn": espn_refresh,
        "sportsdataio": sportsdataio_refresh,
        "nba_summer_league": summer_league_refresh,
        "pandascore": pandascore_refresh,
        "imported": imported,
        "fetched_rows": fetched_rows,
        "errors": (
            espn_refresh.get("errors", [])
            + sportsdataio_refresh.get("errors", [])
            + summer_league_refresh.get("errors", [])
            + pandascore_refresh.get("errors", [])
        ),
    }


def _refresh_and_settle_complete_board() -> dict:
    targets = BoardOfferRepository.settlement_entries(limit=1000)
    refresh = _refresh_final_stats(targets) if targets else {
        "skipped": True,
        "reason": "No complete-board offers are due for final-stat retrieval.",
        "imported": 0,
    }
    settlement = BoardOfferRepository.settle_pending(limit=2000)
    return {
        "targeted_offers": sum(len(entry.get("props") or []) for entry in targets),
        "provider_refresh": refresh,
        "settlement": settlement,
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
            if legs and all(prop.get("actual") is None for prop in entry.get("props", [])):
                EntryRepository.store_settled_leg_results(entry["id"], legs)
                ResearchEvidenceRepository.record_outcome({**entry, "props": legs})
                backfilled += 1
                leg_rows += len(legs)
            continue
        EntryRepository.store_settled_leg_results(entry["id"], legs)
        ResearchEvidenceRepository.record_outcome({**entry, "props": legs})
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

    if os.getenv("EDGEIQ_TRUST_SPORTSDATAIO_FINALS", "").strip().lower() not in {"1", "true", "yes"}:
        return {
            "provider": "sportsdataio",
            "skipped": True,
            "sports": [],
            "dates": [],
            "fetched_rows": 0,
            "imported": 0,
            "errors": [],
            "reason": "SportsDataIO settlement is disabled until a production-data feed is confirmed.",
        }

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
        dates = [datetime.now(UTC).date()]
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
            "message": f"Could not import {path.name}. Check that the file is readable and formatted correctly.",
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
    if payload.standard_batch and str(payload.sport or "").strip().lower() in {"", "all sports"}:
        return _balanced_all_sports_paper_calibration(payload)
    entries = EntryRepository.all()
    backtest_data = backtest_summary(BetRepository().get_all(), entries)
    targets = _calibration_learning_targets(
        backtest_data,
        payload.sport,
        PredictionLedgerRepository.evidence_rows(include_legacy=False),
    )
    existing_signatures = {
        _entry_signature(entry)
        for entry in EntryRepository.pending()
        if str(entry.get("entry_mode", "real")).lower() == "paper"
    }
    pending_paper_count = len(existing_signatures)
    created: list[dict] = []
    skipped: list[dict] = []
    prop_pool_cache: dict[tuple[str, str], list[dict]] = {}
    analyzed_cache: dict[tuple, dict] = {}

    if payload.standard_batch:
        _create_standard_calibration_batch(
            payload,
            targets,
            backtest_data,
            existing_signatures,
            created,
            skipped,
            prop_pool_cache,
            analyzed_cache,
        )
    else:
        for target in targets:
            if len(created) >= payload.max_entries:
                break
            suggestions = _paper_calibration_suggestions(payload, target, prop_pool_cache, analyzed_cache)
            if not suggestions:
                skipped.append({**target, "reason": "No current props matched this calibration target."})
                continue

            for suggestion in suggestions:
                if len(created) >= payload.max_entries:
                    break
                if _append_calibration_entry(
                    suggestion,
                    target,
                    payload,
                    backtest_data,
                    existing_signatures,
                    created,
                    skipped,
                ):
                    continue

    requested_plan = (
        list(payload.batch_plan or [2, 2, 3, 4, 5])
        if payload.standard_batch
        else [payload.leg_count] * payload.max_entries
    )
    board_diagnostics = _auto_paper_board_diagnostics(prop_pool_cache, pending_paper_count)

    return {
        "created": created,
        "created_count": len(created),
        "requested_count": len(requested_plan),
        "requested_plan": requested_plan,
        "created_plan": [int(row["suggestion"].get("leg_count") or 0) for row in created],
        "shortfall": max(0, len(requested_plan) - len(created)),
        "dry_run": payload.dry_run,
        "targets": targets,
        "skipped": skipped,
        "board_diagnostics": board_diagnostics,
        "dashboard": get_dashboard() if not payload.dry_run else None,
    }


def _balanced_all_sports_paper_calibration(payload: AutoPaperCalibrationPayload) -> dict:
    raw_props = _fetch_props("Both", None)
    active_sports = _available_prop_sports(raw_props)
    sport_results: list[dict] = []
    created: list[dict] = []
    skipped: list[dict] = []
    targets: list[dict] = []
    for sport in active_sports:
        sport_props = [
            prop for prop in raw_props
            if str(prop.get("league") or prop.get("sport") or "").upper() == sport
        ]
        provider_counts = {
            provider: len(_paper_calibration_prop_pool([
                prop for prop in sport_props
                if _canonical_platform(prop.get("platform") or "") == provider
            ], sport))
            for provider in ("PrizePicks", "Underdog")
        }
        available_providers = [provider for provider, count in provider_counts.items() if count >= 2]
        if not available_providers:
            sport_results.append({
                "sport": sport,
                "created_count": 0,
                "created_plan": [],
                "shortfall": 5,
                "eligible_same_day_props": sum(provider_counts.values()),
                "providers": [],
            })
            continue

        plan = [2, 2, 3, 4, 5]
        if len(available_providers) > 1:
            rotate = datetime.now(ENTRY_DAY_TIME_ZONE).date().toordinal() % 2
            ordered_providers = available_providers[rotate:] + available_providers[:rotate]
            assigned_counts = {provider: 0 for provider in ordered_providers}
            assignments = []
            for leg_count in plan:
                capable = [provider for provider in ordered_providers if provider_counts[provider] >= leg_count]
                candidates = capable or ordered_providers
                provider = min(candidates, key=lambda name: (assigned_counts[name], ordered_providers.index(name)))
                assignments.append(provider)
                assigned_counts[provider] += 1
        else:
            assignments = [available_providers[0]] * len(plan)

        provider_results = []
        result_parts = []
        for provider in available_providers:
            provider_plan = [legs for legs, assigned in zip(plan, assignments, strict=True) if assigned == provider]
            if not provider_plan:
                continue
            provider_result = _auto_paper_calibration(payload.model_copy(update={
                "platform": provider,
                "sport": sport,
                "max_entries": len(provider_plan),
                "batch_plan": provider_plan,
            }))
            result_parts.append(provider_result)
            provider_results.append({
                "platform": provider,
                "created_count": provider_result["created_count"],
                "requested_count": len(provider_plan),
                "created_plan": provider_result["created_plan"],
                "eligible_same_day_props": provider_counts[provider],
            })

        sport_created = [row for result in result_parts for row in result["created"]]
        sport_skipped = [row for result in result_parts for row in result["skipped"]]
        sport_targets = [row for result in result_parts for row in result["targets"]]
        sport_created_plan = [int(row["suggestion"].get("leg_count") or 0) for row in sport_created]
        sport_results.append({
            "sport": sport,
            "created_count": len(sport_created),
            "created_plan": sport_created_plan,
            "shortfall": max(0, 5 - len(sport_created)),
            "eligible_same_day_props": sum(provider_counts.values()),
            "providers": provider_results,
        })
        created.extend(sport_created)
        skipped.extend({**row, "sport": row.get("sport") or sport} for row in sport_skipped)
        targets.extend(sport_targets)
    requested_plan = [leg for _sport in active_sports for leg in (2, 2, 3, 4, 5)]
    return {
        "created": created,
        "created_count": len(created),
        "requested_count": len(requested_plan),
        "requested_plan": requested_plan,
        "created_plan": [int(row["suggestion"].get("leg_count") or 0) for row in created],
        "shortfall": max(0, len(requested_plan) - len(created)),
        "dry_run": payload.dry_run,
        "targets": targets,
        "skipped": skipped,
        "sports_requested": active_sports,
        "sport_results": sport_results,
        "board_diagnostics": {
            "eligible_same_day_props": sum(row["eligible_same_day_props"] for row in sport_results),
            "sports": active_sports,
            "pending_paper_cards": len([
                entry for entry in EntryRepository.pending()
                if str(entry.get("entry_mode", "real")).lower() == "paper"
            ]),
            "minimum_props_for_full_batch": 5,
        },
        "dashboard": get_dashboard() if not payload.dry_run else None,
    }


def _auto_paper_board_diagnostics(
    prop_pool_cache: dict[tuple[str, str], list[dict]],
    pending_paper_count: int,
) -> dict:
    pools = [prop for props in prop_pool_cache.values() for prop in props]
    unique_markets = {
        (
            canonical_person_key(prop.get("player")),
            _settlement_stat_key(prop.get("stat")),
            _canonical_platform(prop.get("platform") or ""),
            round(float(prop.get("line") or 0.0), 2),
        )
        for prop in pools
    }
    return {
        "eligible_same_day_props": len(unique_markets),
        "sports": _available_prop_sports(pools),
        "pending_paper_cards": pending_paper_count,
        "minimum_props_for_full_batch": 5,
    }


def _run_automatic_paper_samples() -> dict:
    payload = AutoPaperCalibrationPayload(
        platform="Both",
        sport="All Sports",
        max_entries=5,
        standard_batch=True,
        prefer_confirmed=True,
        dry_run=False,
    )
    result = _auto_paper_calibration(payload)
    result["automatic"] = True
    SettingsRepository.set("auto_paper_samples:last_result", json.dumps({
        "ran_at": iso_utc(utc_now()),
        "created_count": result.get("created_count", 0),
        "requested_count": result.get("requested_count", 0),
        "sports_requested": result.get("sports_requested", []),
        "sport_results": result.get("sport_results", []),
    }, default=str))
    result["message"] = (
        f"Created {result['created_count']} automatic paper calibration cards across {len(result.get('sports_requested') or [])} active sports."
        if result["created_count"]
        else "No automatic paper cards were created because today's verified board could not fill a new unique card."
    )
    return result


def _paper_calibration_status_payload() -> dict:
    now = datetime.now(ENTRY_DAY_TIME_ZONE)
    today = now.date()
    schedule = _refresh_schedule_payload()["schedule"]
    last_result = _safe_json_loads(SettingsRepository.get("auto_paper_samples:last_result", ""))
    entries = []
    for entry in EntryRepository.all():
        if str(entry.get("entry_mode") or "real").lower() != "paper":
            continue
        audit = _safe_json_loads(entry.get("audit_snapshot", ""))
        if audit.get("source") != "auto_paper_calibration":
            continue
        placed_at = entry.get("placed_at") or entry.get("created_at")
        if isinstance(placed_at, str):
            with suppress(ValueError):
                placed_at = datetime.fromisoformat(placed_at.replace("Z", "+00:00"))
        if not isinstance(placed_at, datetime):
            continue
        if placed_at.tzinfo is None:
            placed_at = placed_at.replace(tzinfo=UTC)
        if placed_at.astimezone(ENTRY_DAY_TIME_ZONE).date() == today:
            entries.append(entry)

    def blocked(entry: dict) -> bool:
        unresolved = [prop for prop in entry.get("props", []) if prop.get("actual") is None]
        return bool(unresolved) and any(
            not _end_to_end_prop_eligibility(prop)["eligible"]
            or _automatic_final_retry_expired(prop)
            for prop in unresolved
        )

    waiting = [entry for entry in entries if entry.get("status") != "Settled" and not blocked(entry)]
    blocked_entries = [entry for entry in entries if entry.get("status") != "Settled" and blocked(entry)]
    settled = [entry for entry in entries if entry.get("status") == "Settled"]
    sports = list(last_result.get("sports_requested") or [])
    for entry in entries:
        for prop in entry.get("props", []):
            sport = str(prop.get("sport") or "").upper()
            if sport and sport not in sports:
                sports.append(sport)
    result_by_sport = {row.get("sport"): row for row in last_result.get("sport_results", [])}
    sport_rows = []
    for sport in sports:
        cards = [entry for entry in entries if sport in {str(prop.get("sport") or "").upper() for prop in entry.get("props", [])}]
        result = result_by_sport.get(sport, {})
        created = len(cards) if cards else int(result.get("created_count") or 0)
        sport_rows.append({
            "sport": sport,
            "created": created,
            "target": 5,
            "coverage": round(min(100.0, created / 5 * 100.0), 1),
            "waiting": sum(entry in waiting for entry in cards),
            "settled": sum(entry in settled for entry in cards),
            "blocked": sum(entry in blocked_entries for entry in cards),
            "providers": result.get("providers", []),
            "shortfall": max(0, 5 - created),
        })

    next_run = None
    if schedule.get("enabled", True):
        try:
            hour, minute = [int(part) for part in str(schedule.get("auto_paper_samples") or "08:30").split(":", 1)]
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            last_run = str(SettingsRepository.get("daily_scheduler_run:auto_paper_samples", ""))
            if candidate <= now or last_run.startswith(today.isoformat()):
                candidate += timedelta(days=1)
            next_run = candidate.isoformat()
        except (TypeError, ValueError):
            next_run = None

    alerts = [
        f"{row['sport']} produced {row['created']} of 5 cards because only verified same-day offers are allowed."
        for row in sport_rows if row["shortfall"]
    ]
    return {
        "date": today.isoformat(),
        "next_run_at": next_run,
        "scheduler_enabled": bool(schedule.get("enabled", True)),
        "last_run_at": last_result.get("ran_at") or SettingsRepository.get("daily_scheduler_run:auto_paper_samples", ""),
        "sports": sport_rows,
        "totals": {
            "created": len(entries) if entries else sum(int(row.get("created_count") or 0) for row in last_result.get("sport_results", [])),
            "waiting": len(waiting),
            "settled": len(settled),
            "blocked": len(blocked_entries),
        },
        "alerts": alerts,
        "explanation": "Each settled paper prop becomes an independent outcome used to measure confidence, sport, stat, and provider calibration without risking bankroll.",
    }


def _create_standard_calibration_batch(
    payload: AutoPaperCalibrationPayload,
    targets: list[dict],
    backtest_data: dict,
    existing_signatures: set[tuple],
    created: list[dict],
    skipped: list[dict],
    prop_pool_cache: dict[tuple[str, str], list[dict]],
    analyzed_cache: dict[tuple, dict],
) -> None:
    plan = list(payload.batch_plan or [2, 2, 3, 4, 5])
    confidence_targets = [target for target in targets if target.get("type") == "Confidence"]
    other_targets = [target for target in targets if target.get("type") != "Confidence"]
    ordered_targets = confidence_targets + other_targets
    used_targets: set[tuple[str, str, str]] = set()

    for leg_count in plan:
        slot_payload = payload.model_copy(update={"leg_count": leg_count, "max_entries": 1})
        fresh_targets = [target for target in ordered_targets if _calibration_target_key(target) not in used_targets]
        candidate_targets = fresh_targets + [target for target in ordered_targets if target not in fresh_targets]
        created_for_slot = False
        for target in candidate_targets:
            suggestions = _paper_calibration_suggestions(slot_payload, target, prop_pool_cache, analyzed_cache)
            for suggestion in suggestions:
                if _append_calibration_entry(
                    suggestion,
                    target,
                    slot_payload,
                    backtest_data,
                    existing_signatures,
                    created,
                    skipped,
                ):
                    used_targets.add(_calibration_target_key(target))
                    created_for_slot = True
                    break
            if created_for_slot:
                break
        if not created_for_slot:
            skipped.append({
                "type": "BatchSlot",
                "name": f"{leg_count}-leg",
                "reason": (
                    f"The current verified board did not contain a unique {leg_count}-leg card "
                    "for an available calibration target."
                ),
            })


def _calibration_target_key(target: dict) -> tuple[str, str, str]:
    return (
        str(target.get("type") or ""),
        str(target.get("name") or ""),
        str(target.get("sport") or ""),
    )


def _append_calibration_entry(
    suggestion,
    target: dict,
    payload: AutoPaperCalibrationPayload,
    backtest_data: dict,
    existing_signatures: set[tuple],
    created: list[dict],
    skipped: list[dict],
) -> bool:
    serialized = _serialize_suggestion(suggestion)
    signature = _entry_signature(serialized["entry"])
    if signature in existing_signatures:
        skipped.append({**target, "reason": "A matching pending paper entry already exists."})
        return False
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
    return True


def _calibration_learning_targets(
    backtest_data: dict,
    selected_sport: str,
    prediction_rows: list[dict] | None = None,
) -> list[dict]:
    targets: list[dict] = []
    sport = None if selected_sport == "All Sports" else selected_sport.upper()
    ledger_rows = prediction_rows or []

    for bucket in backtest_data.get("calibration", []):
        bets = int(bucket.get("bets") or 0)
        error = abs(float(bucket.get("error") or 0.0))
        bounds = _confidence_bucket_bounds(bucket.get("label", ""))
        if bounds is None or (bets >= 25 and error < 12):
            continue
        low, high = bounds
        targets.append({
            "type": "Confidence",
            "name": f"{low:g}-{high:g}%",
            "sport": sport,
            "confidence_low": low,
            "confidence_high": high,
            "sample_size": bets,
            "calibration_error": round(error, 1),
            "priority": 220 + min(100, int(error * 1.5)) + max(0, 25 - bets),
            "reason": f"Confidence bucket {low:g}-{high:g}% has {bets} samples and {error:.1f} pts calibration error.",
        })

    for segment in backtest_data.get("what_fails", []):
        segment_type = segment.get("type", "")
        name = str(segment.get("name", "")).strip()
        if not name or segment_type not in {"Sport", "Stat", "Platform"}:
            continue
        target = {
            "type": segment_type,
            "name": name,
            "sport": name.upper() if segment_type == "Sport" and name.upper() in SUPPORTED_SPORTS else sport,
            "priority": 130 - min(60, int(segment.get("tracked") or 0) * 4),
            "reason": f"{segment_type} {name} is underperforming: {segment.get('win_rate', 0)}% win rate, {segment.get('roi', 0)}% ROI.",
        }
        targets.append(target)

    targets.extend(_weak_ledger_segment_targets(ledger_rows, sport))

    targets.append({
        "type": "Coverage",
        "name": sport or "Confirmed board",
        "sport": sport,
        "priority": 60 if sport else 50,
        "reason": (
            f"Add end-to-end verified {sport} samples after the weakest confidence buckets are covered."
            if sport
            else "Use the cleanest current board when weak historical segments are unavailable today."
        ),
    })

    unique: dict[tuple[str, str, str], dict] = {}
    for target in targets:
        key = (target.get("type", ""), target.get("name", ""), target.get("sport") or "")
        if key not in unique or int(target.get("priority", 0)) > int(unique[key].get("priority", 0)):
            unique[key] = target
    ordered = sorted(unique.values(), key=lambda target: int(target.get("priority", 0)), reverse=True)
    # Always retain a verified-board fallback. Historical weak buckets can be
    # impossible to sample from today's calibrated probability distribution.
    coverage = next((target for target in ordered if target.get("type") == "Coverage"), None)
    selected = [target for target in ordered if target.get("type") != "Coverage"][:7]
    if coverage is not None:
        selected.append(coverage)
    return selected


def _weak_ledger_segment_targets(rows: list[dict], sport: str | None) -> list[dict]:
    groups: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for row in deduplicate_outcomes(rows):
        if row.get("result") not in {"Win", "Loss"}:
            continue
        row_sport = str(row.get("sport") or "").upper()
        if sport and row_sport != sport:
            continue
        key = (
            row_sport,
            str(row.get("stat") or ""),
            str(row.get("platform") or ""),
            str(row.get("direction") or "Over"),
            str(row.get("projection_source") or ""),
        )
        groups.setdefault(key, []).append(row)
    targets = []
    for (row_sport, stat, platform, direction, projection_source), sample in groups.items():
        predicted = sum(float(row.get("probability") or 50.0) for row in sample) / len(sample)
        actual = sum(1 for row in sample if row.get("result") == "Win") / len(sample) * 100.0
        error = abs(actual - predicted)
        if len(sample) >= 50 and error < 10:
            continue
        targets.append({
            "type": "ModelSegment",
            "name": f"{row_sport} · {stat} · {platform} · {direction}",
            "sport": row_sport,
            "stat": stat,
            "platform": platform,
            "direction": direction,
            "projection_source": projection_source,
            "sample_size": len(sample),
            "calibration_error": round(error, 1),
            "priority": 150 + min(25, max(0, 50 - len(sample))) + min(75, int(error)),
            "reason": (
                f"{row_sport} {stat} {direction} on {platform} has {len(sample)} independent results "
                f"and {error:.1f} points of calibration error."
            ),
        })
    return targets


def _confidence_bucket_bounds(label: object) -> tuple[float, float] | None:
    values = re.findall(r"\d+(?:\.\d+)?", str(label or ""))
    if len(values) < 2:
        return None
    low, high = float(values[0]), float(values[1])
    if low < 0 or high <= low or high > 100:
        return None
    return low, high


def _paper_calibration_suggestions(
    payload: AutoPaperCalibrationPayload,
    target: dict,
    prop_pool_cache: dict[tuple[str, str], list[dict]] | None = None,
    analyzed_cache: dict[tuple, dict] | None = None,
) -> list:
    sport = target.get("sport") or (None if payload.sport == "All Sports" else payload.sport.upper())
    pool_key = (_canonical_platform(payload.platform), sport or "ALL")
    prop_pool_cache = prop_pool_cache if prop_pool_cache is not None else {}
    if pool_key not in prop_pool_cache:
        prop_pool_cache[pool_key] = _paper_calibration_prop_pool(_fetch_props(payload.platform, sport), sport)
    raw_props = prop_pool_cache[pool_key]
    source = "end_to_end_verified"
    if sport is None:
        sport = _dominant_sport(raw_props)
        raw_props = [prop for prop in raw_props if str(prop.get("league") or prop.get("sport") or "").upper() == sport]

    if sport is None:
        sport = _dominant_sport(raw_props)
    if sport is None and payload.sport == "All Sports":
        for candidate_sport in _available_prop_sports(raw_props):
            scoped_props = [prop for prop in raw_props if str(prop.get("league", "")).upper() == candidate_sport]
            suggestions = _paper_calibration_suggestions_for_props(payload, target, scoped_props, candidate_sport, analyzed_cache)
            if suggestions:
                for suggestion in suggestions:
                    suggestion.source = source
                return suggestions

    if not sport:
        return []

    suggestions = _paper_calibration_suggestions_for_props(payload, target, raw_props, sport, analyzed_cache)
    for suggestion in suggestions:
        suggestion.source = source
    return suggestions


def _paper_calibration_suggestions_for_props(
    payload: AutoPaperCalibrationPayload,
    target: dict,
    raw_props: list[dict],
    sport: str,
    analyzed_cache: dict[tuple, dict] | None = None,
) -> list:
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
    elif target.get("type") == "Confidence":
        low = float(target.get("confidence_low") or 0.0)
        high = float(target.get("confidence_high") or 100.0)
        bucket_props = []
        for prop in raw_props:
            analyzed = _cached_paper_prop_analysis(prop, analyzed_cache)
            confidence = float(analyzed.get("confidence") or 0.0)
            if confidence < low or confidence > high or (confidence == high and high < 100):
                continue
            bucket_props.append({
                **prop,
                "projection": analyzed.get("projection"),
                "direction": analyzed.get("direction"),
                "source_score": analyzed.get("confidence"),
            })
        raw_props = bucket_props
    elif target.get("type") == "ModelSegment":
        segment_props = []
        for prop in raw_props:
            if target.get("stat") and stat_type_from_text(prop.get("stat", "")).value != stat_type_from_text(target["stat"]).value:
                continue
            if target.get("platform") and _canonical_platform(prop.get("platform", payload.platform)) != _canonical_platform(target["platform"]):
                continue
            analyzed = _cached_paper_prop_analysis(prop, analyzed_cache)
            if target.get("direction") and str(analyzed.get("direction") or "Over") != target["direction"]:
                continue
            if target.get("projection_source") and str(analyzed.get("projection_source") or "") != target["projection_source"]:
                continue
            segment_props.append({
                **prop,
                "projection": analyzed.get("projection"),
                "direction": analyzed.get("direction"),
                "projection_source": analyzed.get("projection_source"),
                "forecast_probability": analyzed.get("confidence"),
                "forecast_direction": analyzed.get("direction"),
                "forecast_snapshot": analyzed.get("forecast_snapshot") or {},
                "auto_projected": analyzed.get("auto_projected", True),
            })
        raw_props = segment_props

    suggestions = suggest_entries(
        raw_props,
        sport,
        _entry_platform_from_text(payload.platform),
        limit=5,
        leg_count=payload.leg_count,
        min_confidence=0,
        min_edge=-999,
        max_same_team=1 if payload.leg_count <= 3 else 2,
        # Larger paper cards measure individual weak segments. They may share a
        # game when today's slate cannot provide four or five independent legs.
        exclude_correlated=payload.leg_count <= 3,
        apply_feedback=True,
    )
    if target.get("type") == "Confidence":
        low = float(target.get("confidence_low") or 0.0)
        high = float(target.get("confidence_high") or 100.0)
        suggestions = [
            suggestion
            for suggestion in suggestions
            if not getattr(suggestion, "entry", None)
            or (
                suggestion.entry.props
                and all(
                    low <= float(prop.confidence or 0.0) < high
                    or (high == 100 and float(prop.confidence or 0.0) == high)
                    for prop in suggestion.entry.props
                )
            )
        ]
    return suggestions


def _paper_calibration_prop_pool(raw_props: list[dict], sport: str | None, limit: int = 300) -> list[dict]:
    eligible = [
        prop for prop in raw_props
        if _end_to_end_prop_eligibility(prop)["eligible"]
        and _is_prop_on_entry_day(prop)
        and (not sport or str(prop.get("league") or prop.get("sport") or "").upper() == sport)
    ]
    eligible.sort(key=lambda prop: int(prop.get("trending_count") or 0), reverse=True)
    unique: list[dict] = []
    seen: set[tuple] = set()
    for prop in eligible:
        key = (
            canonical_person_key(prop.get("player")),
            _settlement_stat_key(prop.get("stat")),
            _canonical_platform(prop.get("platform") or ""),
            round(float(prop.get("line") or 0.0), 2),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(prop)
        if len(unique) >= limit:
            break
    return unique


def _cached_paper_prop_analysis(prop: dict, cache: dict[tuple, dict] | None) -> dict:
    if cache is None:
        return _analyzed_feed_prop(prop)
    key = (
        canonical_person_key(prop.get("player")),
        _settlement_stat_key(prop.get("stat")),
        _canonical_platform(prop.get("platform") or ""),
        round(float(prop.get("line") or 0.0), 2),
    )
    if key not in cache:
        cache[key] = _analyzed_feed_prop(prop)
    return cache[key]


def _available_prop_sports(raw_props: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for prop in raw_props:
        sport = str(prop.get("sport") or prop.get("league") or "").upper()
        if sport:
            counts[sport] = counts.get(sport, 0) + 1
    return [
        sport for sport, _count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        if sport in SUPPORTED_SPORTS
    ]


def _paper_calibration_audit(suggestion: dict, target: dict, backtest_data: dict, payload: AutoPaperCalibrationPayload) -> dict:
    return {
        "schema_version": AUDIT_SNAPSHOT_SCHEMA_VERSION,
        "model_version": EDGEIQ_LOCAL_MODEL_VERSION,
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
        "note": "Auto-created from end-to-end verified props as a zero-wager paper entry targeting a weak calibration segment. It has no bankroll impact.",
    }


def _entry_signature(entry: dict) -> tuple:
    return tuple(sorted(
        (
            canonical_person_key(prop.get("player")),
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
        final_imported = import_final_stats(text, payload.source or "upload")
        return {
            "kind": "final_stats",
            "file_name": payload.file_name,
            "imported": final_imported,
            "message": f"Imported {final_imported} final stat rows.",
        }
    if payload.target == "bet_history":
        rows = _parse_betting_history(text)
        bet_import = _import_betting_rows(rows, payload.source or "upload")
        return {
            "kind": "bet_history",
            "file_name": payload.file_name,
            **bet_import,
            "message": f"Imported {bet_import['imported']} bets. Skipped {bet_import['skipped']}.",
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
        extracted = _ollama_extract_bets_from_image(raw)
        extraction_method = "ollama_vision"
        if extracted is None:
            extracted = _openai_extract_bets_from_image(raw, payload.mime_type or "image/png")
            extraction_method = "openai"
        if extracted is None:
            ocr_text = _local_ocr_image(raw, payload.file_name)
            return {
                "kind": "bet_history",
                "file_name": payload.file_name,
                "imported": 0,
                "skipped": 0,
                "ai_enabled": False,
                "local_ocr": bool(ocr_text),
                "ocr_text": ocr_text,
                "message": (
                    "Local OCR read the screenshot, but settled bet history still needs review before import."
                    if ocr_text
                    else "The screenshot could not be read locally. Try a clearer image, or connect OpenAI for enhanced extraction."
                ),
            }
        rows = extracted.get("bets", [])
        imported = _import_betting_rows(rows, extracted.get("platform") or payload.source or "screenshot")
        return {
            "kind": "bet_history",
            "file_name": payload.file_name,
            **imported,
            "ai_enabled": True,
            "extraction_method": extraction_method,
            "raw_ai": extracted,
            "message": f"Imported {imported['imported']} bets from screenshot. Skipped {imported['skipped']}.",
        }

    extracted = _ollama_extract_props_from_image(raw)
    extraction_method = "ollama_vision"
    if extracted is None:
        extracted = _openai_extract_props_from_image(raw, payload.mime_type or "image/png")
        extraction_method = "openai"
    if extracted is None:
        extracted = _local_extract_props_from_image(raw, payload.file_name, payload.source)
        extraction_method = "local_ocr"
    if extracted is None:
        return {
            "kind": "image",
            "file_name": payload.file_name,
            "props": [],
            "prop_count": 0,
            "analysis": None,
            "ai_enabled": False,
            "local_ocr": False,
            "message": "The screenshot could not be read locally. Try a clearer crop, or connect OpenAI for enhanced extraction.",
        }

    extracted_rows = extracted.get("props", [])
    extracted_platform = extracted.get("platform") or payload.source or "Upload"
    normalized_props = _normalize_uploaded_props(extracted_rows, extracted_platform)
    props, rejected = _verified_screenshot_props(
        normalized_props,
        extracted_platform,
        trust_provider_rows=extraction_method == "local_ocr",
    )
    duplicates_removed = max(0, len(extracted_rows) - len(normalized_props))
    analysis = _analysis_from_uploaded_props(props)
    return {
        "kind": "image",
        "file_name": payload.file_name,
        "props": props,
        "prop_count": len(props),
        "duplicates_removed": duplicates_removed,
        "rejected_unverified": rejected,
        "analysis": analysis,
        "ai_enabled": extraction_method in {"openai", "ollama_vision"},
        "local_ocr": extraction_method == "local_ocr",
        "extraction_method": extraction_method,
        "ocr_text": extracted.get("ocr_text", "") if extraction_method == "local_ocr" else "",
        "raw_ai": extracted if extraction_method == "openai" else None,
        "message": (
            f"Verified {len(props)} provider-backed picks with on-device OCR."
            if extraction_method == "local_ocr"
            else f"Verified {len(props)} provider-backed picks using {extraction_method.replace('_', ' ')}."
        ),
    }


def _local_extract_props_from_image(raw: bytes, file_name: str, source: str) -> dict | None:
    text = _local_ocr_image(raw, file_name)
    if not text:
        return None
    platform = _platform_from_ocr_text(text, source)
    props = _match_ocr_text_to_live_props(text, platform)
    return {
        "platform": platform,
        "props": props,
        "ocr_text": text,
        "notes": (
            ["Matched on-device OCR text against current provider markets."]
            if props
            else ["Text was recognized, but no current provider props matched confidently."]
        ),
    }


def _local_ocr_image(raw: bytes, file_name: str) -> str:
    image_signatures = (
        raw.startswith(b"\x89PNG\r\n\x1a\n"),
        raw.startswith(b"\xff\xd8\xff"),
        raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
    )
    if not any(image_signatures):
        return ""
    script = Path(__file__).resolve().parents[1] / "scripts" / "ocr_image.swift"
    swift = Path("/usr/bin/swift")
    if not script.exists() or not swift.exists():
        return ""
    suffix = Path(file_name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as image_file:
            image_file.write(raw)
            image_file.flush()
            result = subprocess.run(
                [str(swift), str(script), image_file.name],
                capture_output=True,
                check=False,
                text=True,
                timeout=25,
                env={
                    **os.environ,
                    "SWIFT_MODULECACHE_PATH": str(Path(tempfile.gettempdir()) / "edgeiq-swift-cache"),
                    "CLANG_MODULE_CACHE_PATH": str(Path(tempfile.gettempdir()) / "edgeiq-clang-cache"),
                },
            )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _platform_from_ocr_text(text: str, source: str) -> str:
    lowered = text.lower()
    if "prizepicks" in lowered or "prize picks" in lowered:
        return "PrizePicks"
    if "underdog" in lowered:
        return "Underdog"
    if "draftkings" in lowered or "pick6" in lowered or "pick 6" in lowered:
        return "DraftKings Pick6"
    if "sleeper" in lowered:
        return "Sleeper"
    canonical = _canonical_platform(source)
    return canonical if canonical in {"PrizePicks", "Underdog", "DraftKings Pick6", "Sleeper"} else "Both"


def _match_ocr_text_to_live_props(text: str, platform: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text_key = canonical_person_key(" ".join(lines))
    try:
        active_props = _fetch_props(platform, None)
    except Exception:
        return []
    known_players = sorted({str(prop.get("player") or "").strip() for prop in active_props if prop.get("player")})
    matches: list[dict] = []
    seen: set[tuple[str, str, float, str]] = set()
    for prop in active_props:
        player = str(prop.get("player") or "").strip()
        stat = str(prop.get("stat") or "").strip()
        line = prop.get("line")
        if not player or not stat or line is None:
            continue
        player_key = canonical_person_key(player)
        if player_key not in text_key:
            continue
        window = _ocr_player_window(lines, player, known_players)
        if not window or canonical_stat_key(window) != canonical_stat_key(stat):
            continue
        line_value = float(line)
        line_tokens = {f"{line_value:g}", f"{line_value:.1f}"}
        if not any(re.search(rf"(?<!\d){re.escape(token)}(?!\d)", window) for token in line_tokens):
            continue
        direction = _ocr_direction(window)
        if not direction:
            continue
        key = (player_key, _stat_match_key(stat), line_value, direction)
        if key in seen:
            continue
        seen.add(key)
        matches.append({
            **prop,
            "direction": direction,
            "provider_backed": True,
            "projection_source": "local_ocr_provider_match",
        })
    return matches[:12]


def _ocr_player_window(lines: list[str], player: str, known_players: list[str] | None = None) -> str:
    player_key = canonical_person_key(player)
    other_player_keys = {
        canonical_person_key(name)
        for name in (known_players or [])
        if canonical_person_key(name) and canonical_person_key(name) != player_key
    }
    for index, line in enumerate(lines):
        if player_key in canonical_person_key(line):
            end = min(len(lines), index + 7)
            for candidate_index in range(index + 1, end):
                candidate_key = canonical_person_key(lines[candidate_index])
                if any(other_key in candidate_key for other_key in other_player_keys):
                    end = candidate_index
                    break
            return " ".join(lines[index:end])
    return ""


def _ocr_direction(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(less|lower|under)\b", lowered):
        return "Under"
    if re.search(r"\b(more|higher|over)\b", lowered):
        return "Over"
    return ""


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
    source_metadata = {
        _uploaded_prop_match_key(row): row
        for row in rows
        if _uploaded_prop_match_key(row)
    }
    normalized = []
    for prop in props:
        source = source_metadata.get(_uploaded_prop_match_key(prop), {})
        normalized.append(_uploaded_prop_payload({
            **prop,
            "provider_backed": bool(source.get("provider_backed")),
            "projection_source": source.get("projection_source") or prop.get("projection_source") or "",
            "line_offer_type": source.get("line_offer_type") or prop.get("line_offer_type") or "standard",
            "adjusted_line": source.get("adjusted_line") or prop.get("adjusted_line"),
            "is_discounted_line": source.get("is_discounted_line") or prop.get("is_discounted_line"),
            "is_premium_line": source.get("is_premium_line") or prop.get("is_premium_line"),
        }))
    return deduplicate_uploaded_props(normalized)


def _uploaded_prop_match_key(prop: dict) -> tuple[str, str, float] | None:
    try:
        line = round(float(prop.get("line")), 4)
    except (TypeError, ValueError):
        return None
    player = canonical_person_key(prop.get("player") or prop.get("player_name"))
    stat = _stat_match_key(str(prop.get("stat") or prop.get("stat_type") or ""))
    return (player, stat, line) if player and stat else None


def _uploaded_prop_payload(prop: dict) -> dict:
    return {
        "player": prop.get("player", ""),
        "player_provider": prop.get("player_provider") or prop.get("platform", ""),
        "provider_player_id": prop.get("provider_player_id") or prop.get("player_id", ""),
        "team": prop.get("team", ""),
        "position": prop.get("position", ""),
        "sport": prop.get("league", prop.get("sport", "WNBA")) or "WNBA",
        "stat": prop.get("stat", "Points"),
        "line": float(prop.get("line") or 0.0),
        "projection": prop.get("projection"),
        "direction": prop.get("direction") or prop.get("pick") or prop.get("side"),
        "platform": prop.get("platform", "Upload"),
        "game": prop.get("game", ""),
        "game_time": prop.get("game_time", ""),
        "line_offer_type": prop.get("line_offer_type") or prop.get("odds_type") or "standard",
        "adjusted_line": bool(prop.get("adjusted_line") or prop.get("adjusted_odds")),
        "is_discounted_line": bool(prop.get("is_discounted_line")),
        "is_premium_line": bool(prop.get("is_premium_line")),
        "trending_count": int(prop.get("trending_count") or 0),
        "provider_backed": bool(prop.get("provider_backed")),
        "projection_source": prop.get("projection_source") or "",
    }


def _verified_screenshot_props(
    props: list[dict],
    platform: str,
    *,
    trust_provider_rows: bool = False,
) -> tuple[list[dict], int]:
    candidates = [prop for prop in props if _explicit_upload_direction(prop.get("direction"))]
    rejected = len(props) - len(candidates)
    if trust_provider_rows:
        verified = [prop for prop in candidates if prop.get("provider_backed")]
        return deduplicate_uploaded_props(verified), rejected + len(candidates) - len(verified)
    try:
        active_props = _fetch_props(platform, None)
    except Exception:
        return [], len(props)

    verified = []
    for candidate in candidates:
        direction = _explicit_upload_direction(candidate.get("direction"))
        matches = [
            prop
            for prop in active_props
            if canonical_person_key(prop.get("player")) == canonical_person_key(candidate.get("player"))
            and _stat_match_key(str(prop.get("stat") or "")) == _stat_match_key(str(candidate.get("stat") or ""))
            and abs(float(prop.get("line") or 0) - float(candidate.get("line") or 0)) < 0.01
        ]
        if not matches:
            rejected += 1
            continue
        provider_prop = max(
            matches,
            key=lambda prop: (
                int(bool(prop.get("game_time"))),
                int(bool(prop.get("provider_player_id") or prop.get("player_id"))),
            ),
        )
        verified.append({
            **provider_prop,
            "direction": direction,
            "provider_backed": True,
            "projection_source": "screenshot_provider_match",
        })
    return deduplicate_uploaded_props([_uploaded_prop_payload(prop) for prop in verified]), rejected


def _explicit_upload_direction(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"over", "higher", "more", "o"}:
        return "Over"
    if text in {"under", "lower", "less", "u"}:
        return "Under"
    return ""


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
            "\"stat\":\"\",\"line\":0,\"direction\":\"Over|Under\",\"projection\":null,\"game\":\"\"}],"
            "\"notes\":[]}. Use null when a projection is not shown. Do not invent missing props."
        ),
        max_output_tokens=700,
    )


_SCREENSHOT_PROP_SCHEMA = {
    "type": "object",
    "properties": {
        "platform": {"type": "string"},
        "props": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "player": {"type": "string"}, "team": {"type": "string"},
                    "sport": {"type": "string"}, "stat": {"type": "string"},
                    "line": {"type": "number"}, "direction": {"type": "string"},
                    "projection": {"type": ["number", "null"]}, "game": {"type": "string"},
                },
                "required": ["player", "team", "sport", "stat", "line", "direction", "projection", "game"],
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["platform", "props", "notes"],
}

_SCREENSHOT_BET_SCHEMA = {
    "type": "object",
    "properties": {
        "platform": {"type": "string"},
        "bets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sport": {"type": "string"}, "game": {"type": "string"},
                    "description": {"type": "string"}, "odds": {"type": "number"},
                    "wager": {"type": "number"}, "result": {"type": "string"},
                    "profit": {"type": ["number", "null"]}, "stat_type": {"type": "string"},
                    "win_probability": {"type": ["number", "null"]},
                },
                "required": ["sport", "game", "description", "odds", "wager", "result", "profit", "stat_type", "win_probability"],
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["platform", "bets", "notes"],
}


def _ollama_extract_props_from_image(raw: bytes) -> dict | None:
    result, _ = ollama_vision_structured(
        raw,
        "Extract only visible player props. Do not infer or duplicate picks. Return the requested JSON fields.",
        _SCREENSHOT_PROP_SCHEMA,
    )
    return result


def _ollama_extract_bets_from_image(raw: bytes) -> dict | None:
    result, _ = ollama_vision_structured(
        raw,
        "Extract only visible settled bets. Do not infer results or duplicate bets. Return the requested JSON fields.",
        _SCREENSHOT_BET_SCHEMA,
    )
    return result


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


def _assistant_parlay_response(
    message: str,
    suggestions: list[dict],
    request: dict | None = None,
) -> tuple[str | None, str | None, str, str]:
    if not suggestions:
        return None, "No verified candidates are available for the AI to review.", "EdgeIQ Local", EDGEIQ_LOCAL_MODEL_VERSION
    messages = [
        {
            "role": "system",
            "content": (
                "You are EdgeIQ's local betting research assistant. EdgeIQ has already selected the one supplied card; "
                "explain that exact card and do not replace, add, or remove legs. "
                "Never invent players, lines, odds, probabilities, injuries, or guaranteed outcomes. Treat EdgeIQ's "
                "computed fields as the only available evidence and do not use outside knowledge. Opponent names are "
                "labels, not defensive evidence. Matchup history always describes the selected player's own results; "
                "never rephrase it as points allowed, opponent defense, containment, or an opponent weakness. "
                "Never characterize an opponent or claim that a team struggled. "
                "If a field is missing, say it is unavailable. Include every leg's Over or Under direction, explain "
                "opponent-history or data-quality context only when supplied, identify the main risk, "
                "and remind the user that no entry is guaranteed. Keep the answer under 220 words."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_message": message,
                    "request": request or {},
                    "candidates": [_llm_candidate_context(row) for row in suggestions[:5]],
                },
                default=str,
            ),
        },
    ]
    text, ollama_error = ollama_chat(messages, timeout=45)
    if text and _unsupported_ollama_matchup_claim(text):
        revised_messages = messages + [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    "Revise the answer. You incorrectly characterized an opponent. Matchup values are only the "
                    "selected player's own historical results. Do not mention defense, points allowed, containment, "
                    "team strength, or unsupported prior performance."
                ),
            },
        ]
        text, ollama_error = ollama_chat(revised_messages, timeout=45)
        if text and _unsupported_ollama_matchup_claim(text):
            text = None
            ollama_error = "Ollama added unsupported matchup context, so EdgeIQ used its grounded rules-based answer."
    if text:
        return text, None, "Ollama", ollama_model()
    text, openai_error = _openai_parlay_response(message, suggestions, request)
    if text:
        return text, None, "OpenAI", _openai_model()
    error = openai_error if os.getenv("OPENAI_API_KEY", "").strip() else ollama_error
    return None, error, "EdgeIQ Local", EDGEIQ_LOCAL_MODEL_VERSION


def _unsupported_ollama_matchup_claim(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        phrase in lowered
        for phrase in (
            "points allowed", "rebounds allowed", "assists allowed", "opponent defense",
            "defensive record", "defensive matchup", "struggled to contain", "weaker defense",
            "stronger defense", "team weakness", "opponent's performance", "opponent performance",
        )
    )


def _llm_candidate_context(suggestion: dict) -> dict:
    props = (suggestion.get("entry") or {}).get("props") or []
    return {
        key: suggestion.get(key)
        for key in ("rank", "grade", "action", "score", "risk_tier", "model_trust", "warnings")
    } | {
        "props": [
            {
                key: prop.get(key)
                for key in (
                    "player", "team", "sport", "stat", "direction", "line", "projection",
                    "confidence", "edge", "platform", "game", "data_strength", "data_quality",
                )
            } | {
                "player_matchup_history": {
                    "opponent": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent"),
                    "verified_player_games": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent_sample"),
                    "player_average_for_this_stat": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent_mean"),
                    "weight_in_projection": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent_adjustment_weight"),
                    "change_to_player_projection": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent_projection_delta"),
                },
                "distribution": {
                    key: ((prop.get("forecast_snapshot") or {}).get("distribution") or {}).get(key)
                    for key in (
                        "expected_result", "median", "floor", "ceiling",
                        "probability_over_exact_line", "probability_under_exact_line", "uncertainty_level",
                    )
                },
            }
            for prop in props
        ],
    }


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


def _assistant_entry_review(question: str, analysis: dict) -> tuple[str | None, str | None, str, str]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are EdgeIQ's local entry reviewer. Use only the supplied analysis. Never invent stats, lines, "
                "injuries, or results and never promise a win. Identify the strongest leg, weakest leg, conflicts, "
                "opponent-history evidence, suggested direction changes or removals, and a concise final action."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"question": question, "analysis": _llm_entry_review_context(analysis)}, default=str),
        },
    ]
    text, ollama_error = ollama_chat(messages, timeout=45)
    if text:
        return text, None, "Ollama", ollama_model()
    text, openai_error = _openai_entry_review(question, analysis)
    if text:
        return text, None, "OpenAI", _openai_model()
    error = openai_error if os.getenv("OPENAI_API_KEY", "").strip() else ollama_error
    return None, error, "EdgeIQ Local", EDGEIQ_LOCAL_MODEL_VERSION


def _llm_entry_review_context(analysis: dict) -> dict:
    return {
        key: analysis.get(key)
        for key in (
            "grade", "action", "score", "risk", "warnings", "corrections",
            "release_verdict", "data_quality", "model_trust", "payout_analysis",
        )
    } | {
        "entry": {
            "platform": (analysis.get("entry") or {}).get("platform"),
            "props": [
                {
                    key: prop.get(key)
                    for key in (
                        "player", "team", "sport", "stat", "direction", "line", "projection",
                        "confidence", "edge", "game", "data_strength", "projection_source",
                    )
                } | {
                    "player_matchup_history": {
                        "opponent": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent"),
                        "verified_player_games": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent_sample"),
                        "player_average_for_this_stat": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent_mean"),
                        "weight_in_projection": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent_adjustment_weight"),
                        "change_to_player_projection": ((prop.get("forecast_snapshot") or {}).get("features") or {}).get("opponent_projection_delta"),
                    },
                    "distribution": {
                        key: ((prop.get("forecast_snapshot") or {}).get("distribution") or {}).get(key)
                        for key in (
                            "expected_result", "median", "floor", "ceiling",
                            "probability_over_exact_line", "probability_under_exact_line", "uncertainty_level",
                        )
                    },
                }
                for prop in ((analysis.get("entry") or {}).get("props") or [])
            ],
        },
    }


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
        return None, _friendly_openai_error(status, detail)
    except requests.RequestException as exc:
        return None, _friendly_openai_error("network", exc.__class__.__name__)


def _openai_error_detail(response) -> str:
    if response is None:
        return "No response body."
    try:
        data = response.json()
        message = data.get("error", {}).get("message")
        return str(message or response.text[:160])
    except ValueError:
        return response.text[:160]


def _friendly_openai_error(status: object, detail: str = "") -> str:
    text = str(detail or "").strip()
    if str(status) == "401":
        return "The AI key was not accepted. Check the OpenAI API key in settings."
    if str(status) == "429":
        return "The AI service is busy or rate-limited. Try again in a moment."
    if str(status) == "network":
        return "The AI service did not respond in time. EdgeIQ used the local review instead."
    if str(status).startswith("5"):
        return "The AI service is having trouble right now. EdgeIQ used the local review instead."
    return text or "The AI review was unavailable, so EdgeIQ used the local review instead."


def _openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5").strip() or "gpt-5"


def _openai_vision_model() -> str:
    return os.getenv("OPENAI_VISION_MODEL", _openai_model()).strip() or _openai_model()



def _record_line_snapshots(props: list[dict], *, force_snapshot: bool = False) -> None:
    seen: set[tuple[str, str, str, str, str]] = set()
    rows = []
    ranked_props = sorted(props, key=lambda prop: prop.get("trending_count", 0), reverse=True)
    for prop in ranked_props:
        line = prop.get("line")
        if line is None:
            continue
        if prop.get("platform") == "PrizePicks" and _prizepicks_offer_type(prop) != "standard":
            continue
        player = prop.get("player", "")
        stat = prop.get("stat", "")
        platform = prop.get("platform", "PrizePicks")
        if not player or not stat:
            continue
        key = (
            canonical_person_key(player),
            stat.strip().lower(),
            platform.strip().lower(),
            canonical_matchup_key(prop.get("game"), EntryRepository.TEAM_ALIASES),
            _prizepicks_offer_type(prop),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "player": player,
            "stat": stat,
            "platform": platform,
            "line": float(line),
            "game": prop.get("game") or "",
            "game_time": prop.get("game_time") or "",
            "line_offer_type": _prizepicks_offer_type(prop),
        })
    if force_snapshot:
        LineHistoryRepository.record_many(rows, force_snapshot=True)
    else:
        LineHistoryRepository.record_many(rows)


def _unique_player_props(props: list[dict], limit: int) -> list[dict]:
    unique: list[dict] = []
    seen: set[str] = set()
    for prop in props:
        key = canonical_person_key(prop.get("player"))
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
        player_key = canonical_person_key(prop.get("player"))
        if not player_key:
            continue
        if any(canonical_person_key(existing.get("player")) == player_key for existing in sport_props):
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
        (canonical_person_key(prop.get("player")), prop.get("league", "").strip().upper())
        for prop in ranked_props
    }
    grouped: dict[tuple[str, str], dict] = {}

    for prop in props:
        game = str(prop.get("game", "")).strip()
        sport = str(prop.get("league", "")).strip().upper()
        if not game or not sport:
            continue
        key = (sport, canonical_matchup_key(game, EntryRepository.TEAM_ALIASES))
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
        if (canonical_person_key(player), sport) in ranked_players:
            player_row["ranked"] = True
            group["ranked_players"][player] = player_row

    games: list[dict] = []
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


def _command_center_payload(
    platform: str,
    sport_filter: str | None,
    *,
    fast: bool = False,
) -> dict:
    dashboard_stats = _cached_dashboard_stats()
    prefs = _user_preferences()
    model = _model_health_payload()
    props = _fetch_props(platform, sport_filter)
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    recommendation_props = _prefer_standard_provider_offers(props)
    optimization_props = _top_props_by_sport(recommendation_props, 8, sport_filter) if fast else recommendation_props
    platform_props = _props_by_platform_from_props(platform, optimization_props)
    ranked_props = [_analyzed_feed_prop(prop) for prop in _top_props_by_sport(recommendation_props, 5, sport_filter)]
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
        platform_props=platform_props,
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
        platform_props=platform_props,
    )
    high_risk_slips = [] if fast else _optimized_entries(
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
        platform_props=platform_props,
    )

    cards = []
    if ranked_props:
        cards.append(_command_single_card(ranked_props[0], model))
    if safe_slips:
        cards.append(_command_suggestion_card("Safer Slip", "Lower volatility entry to start with.", safe_slips[0], model))
    if balanced_slips:
        cards.append(_command_suggestion_card("Best 3-Leg", "Primary daily parlay candidate.", balanced_slips[0], model))
    for suggestion in high_risk_slips[:2]:
        cards.append(_command_suggestion_card(f"Upside {suggestion.entry.prop_count}-Leg", "Higher variance, sized smaller.", suggestion, model))

    avoid = [
        prop for prop in ranked_props
        if prop["confidence"] < 50 or prop["edge"] < 0
    ][:3]
    payload = {
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "as_of": iso_utc(utc_now()),
        "cards": cards[:5],
        "ranked_props": ranked_props[:15],
        "avoid": avoid,
        "model_health": model,
        "preferences": prefs,
        "bankroll": {
            "current": dashboard_stats.get("bankroll", 0.0),
            "pending_exposure": dashboard_stats.get("pending_entry_exposure", 0.0),
            "recommendation_accuracy": dashboard_stats.get("recommendation_accuracy", {}),
        },
    }
    _stamp_current_recommendation_lineage(payload, groups=("cards", "ranked_props", "avoid"))
    return payload


def _new_daily_scan(platform: str, sport_filter: str | None, trigger: str = "manual") -> dict:
    return build_new_daily_scan(platform, sport_filter, trigger)


def _daily_scan_steps(active: str) -> list[dict]:
    return build_daily_scan_steps(active)


def _save_daily_scan_status(scan: dict) -> dict:
    return persist_daily_scan_status(scan, SettingsRepository.set, DAILY_SCAN_STATUS_KEY)


def _recover_interrupted_daily_scan() -> None:
    recover_briefing_scan(
        SettingsRepository.get,
        lambda scan: _save_daily_scan_status(scan),
        _safe_json_loads,
        DAILY_SCAN_STATUS_KEY,
    )


def _update_daily_scan(scan: dict, status: str, message: str, progress: int, **extra) -> dict:
    return update_briefing_scan(
        scan,
        status,
        message,
        progress,
        lambda value: _save_daily_scan_status(value),
        **extra,
    )


def _run_daily_briefing_scan(
    platform: str,
    sport_filter: str | None,
    scan_id: str | None = None,
    trigger: str = "manual",
    sync_result: dict | None = None,
) -> dict:
    with named_operation_lock("daily-briefing-scan") as acquired:
        if not acquired:
            scan = _new_daily_scan(platform, sport_filter, trigger)
            if scan_id:
                scan["id"] = scan_id
            return {
                **scan,
                "status": "failed",
                "status_label": "Already Running",
                "message": "Another Daily Briefing scan is already running.",
                "progress": 100,
                "completed_at": iso_utc(utc_now()),
                "errors": ["Wait for the active scan to finish before starting another refresh."],
            }
        return run_briefing_scan(
            platform,
            sport_filter,
            scan_id=scan_id,
            trigger=trigger,
            sync_result=sync_result,
            create_scan=lambda selected_platform, selected_sport, selected_trigger: _new_daily_scan(
                selected_platform,
                selected_sport,
                selected_trigger,
            ),
            save_status=lambda scan: _save_daily_scan_status(scan),
            update_scan=lambda *args, **kwargs: _update_daily_scan(*args, **kwargs),
            cached_briefing=lambda *args, **kwargs: _cached_daily_briefing_payload(*args, **kwargs),
            append_log=lambda scan: _append_daily_scan_log(scan),
        )


def _daily_scan_summary(briefing: dict) -> dict:
    return build_daily_scan_summary(briefing)


def _append_daily_scan_log(scan: dict) -> None:
    append_briefing_scan_log(
        scan,
        SettingsRepository.get,
        SettingsRepository.set,
        _safe_json_loads,
        DAILY_SCAN_LOG_KEY,
    )


def _daily_scan_status_payload(platform: str, sport_filter: str | None) -> dict:
    return build_daily_scan_status_payload(
        platform,
        sport_filter,
        SettingsRepository.get,
        _safe_json_loads,
        DAILY_SCAN_STATUS_KEY,
        DAILY_SCAN_LOG_KEY,
    )


def _cached_daily_briefing_payload(platform: str, sport_filter: str | None, refresh: bool = False, cached_only: bool = False) -> dict:
    return build_cached_daily_briefing_payload(
        platform,
        sport_filter,
        refresh=refresh,
        cached_only=cached_only,
        cache_version=DAILY_BRIEFING_CACHE_VERSION,
        ttl_hours=DAILY_BRIEFING_CACHE_TTL_HOURS,
        get_setting=SettingsRepository.get,
        set_setting=SettingsRepository.set,
        safe_json_loads=_safe_json_loads,
        build_payload=lambda selected_platform, selected_sport: _daily_briefing_payload(
            selected_platform,
            selected_sport,
        ),
        refresh_runtime_state=lambda payload: _refresh_cached_briefing_runtime_state(payload),
        build_placeholder=lambda selected_platform, selected_sport, key: _daily_briefing_placeholder(
            selected_platform,
            selected_sport,
            key,
        ),
    )


def _refresh_cached_briefing_runtime_state(payload: dict) -> dict:
    protection = _loss_protection_payload()
    sections = {key: list((payload.get("sections") or {}).get(key) or []) for key in ("bet", "paper", "watch", "avoid")}
    if protection.get("active") and sections["bet"]:
        sections["watch"] = _loss_protection_watch_cards(sections["bet"], protection) + sections["watch"]
        sections["bet"] = []
    return {
        **payload,
        "headline": _daily_loss_protection_headline(
            protection,
            sections["bet"],
            sections["paper"],
            sections["watch"],
            sections["avoid"],
        ),
        "loss_protection": protection,
        "sections": sections,
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
        "loss_protection": _loss_protection_payload(),
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
    return briefing_cache_is_fresh(cached, DAILY_BRIEFING_CACHE_TTL_HOURS)


def _daily_briefing_cache_key(platform: str, sport_filter: str | None) -> str:
    return briefing_cache_key(platform, sport_filter)


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
    command = _command_center_payload(platform, sport_filter, fast=True)
    confirmed = _confirmed_props_payload(platform, sport_filter, limit=40, analysis_limit=80)
    loss_protection = _loss_protection_payload()
    candidate_bet_cards = _daily_bet_cards(command["cards"])
    paper_cards = _daily_paper_cards(
        platform,
        sport_filter,
        dashboard_stats,
        command.get("model_health"),
    )
    watch_cards = _daily_watch_cards(platform, sport_filter, command, confirmed)
    avoid_cards = _daily_avoid_cards(command, confirmed)
    if loss_protection["active"]:
        watch_cards = _loss_protection_watch_cards(candidate_bet_cards, loss_protection) + watch_cards
        bet_cards: list[dict] = []
    else:
        bet_cards = candidate_bet_cards
    monthly = dashboard_stats.get("monthly_profit", {})
    current_month = monthly.get("current_month", {})
    top_opportunities = _daily_top_opportunities(command, confirmed)
    risk_summary = _daily_risk_summary(bet_cards, watch_cards, paper_cards)
    games_today = _daily_games_today(platform, sport_filter, confirmed)
    payload = {
        "as_of": iso_utc(utc_now()),
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "user": _daily_user_context(prefs),
        "headline": _daily_loss_protection_headline(loss_protection, bet_cards, paper_cards, watch_cards, avoid_cards),
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
        "loss_protection": loss_protection,
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
            *(loss_protection.get("paid_rules", []) if loss_protection.get("active") else []),
            "Real-money cards are loaded into the entry builder and still require user confirmation.",
            "Paper cards are zero-wager calibration candidates.",
            "Recheck injuries, game time, and line movement before placing.",
        ],
    }
    snapshot = ModelRehabilitationRepository.save_feed(
        {
            "feed": {
                "id": "edgeiq-daily-briefing-v2.2.1",
                "canonical": True,
                "purpose": "Actionable recommendations for Today and Entry Builder.",
                "platform": platform,
                "sport": sport_filter or "All Sports",
            },
            "daily_briefing": payload,
        },
        model_version=EDGEIQ_LOCAL_MODEL_VERSION,
    )
    _stamp_actionable_snapshot(payload, str(snapshot["snapshot_id"]), EDGEIQ_LOCAL_MODEL_VERSION)
    return payload


def _stamp_actionable_snapshot(payload: dict, snapshot_id: str, model_version: str) -> None:
    payload["recommendation_snapshot_id"] = snapshot_id
    payload["model_version"] = model_version
    groups = [
        payload.get("top_opportunities") or [],
        payload.get("suggested_entries") or [],
        *[(payload.get("sections") or {}).get(key) or [] for key in ("bet", "paper", "watch", "avoid")],
    ]
    for group in groups:
        for row in group:
            if isinstance(row, dict):
                row["recommendation_snapshot_id"] = snapshot_id
                row["model_version"] = model_version


def _daily_bet_cards(cards: list[dict]) -> list[dict]:
    entry_cards = [card for card in cards if card.get("type") == "entry"]
    release_ready = [
        card for card in entry_cards
        if (card.get("release_status") or _card_release_status(card))["ok"]
    ]
    return [
        _daily_action_card("bet", card, "Load Slip", _bet_card_reason(card))
        for card in release_ready[:3]
    ]


def _card_release_status(card: dict, model_health: dict | None = None) -> dict:
    props = card.get("props") or []
    trust = card.get("trust") or {}
    trust_score = float(trust.get("score") or 0.0)
    grade = str(card.get("grade") or "").upper()
    action = str(card.get("action") or "")
    blocks: list[str] = []
    warnings: list[str] = []
    if trust_score < 64 or trust.get("label") in {"Paper First", "Pass", "No Data"}:
        blocks.append(f"Trust is {trust.get('label', 'below threshold')} at {trust_score:.0f}.")
    if grade in {"D", "F"} or "Pass" in action:
        blocks.append(f"Entry grade/action is {grade or 'ungraded'} {action}".strip())
    if (model_health or _model_health_payload()).get("paid_entry_mode") != "enabled":
        blocks.append("Model scorecard is not cleared for paid-entry release.")
    segment_flags = _entry_segment_flags(props, card.get("suggestion", {}).get("entry", {}).get("platform") or "")
    blocks.extend(flag["message"] for flag in segment_flags if flag["severity"] == "danger")
    warnings.extend(flag["message"] for flag in segment_flags if flag["severity"] != "danger")
    if any(not prop.get("forecast_paid_eligible") for prop in props):
        blocks.append("Every paid leg must clear forecast-history and segment-calibration evidence thresholds.")
    if any((prop.get("data_quality") or {}).get("label") in {"thin data", "low reliability"} for prop in props):
        warnings.append("One or more legs have thin data history.")
    if any(prop.get("is_premium_line") for prop in props):
        warnings.append("One or more legs use a premium adjusted payout line; verify payout and side before placing.")
    return {"ok": not blocks, "blocks": blocks, "warnings": warnings}


def _daily_top_opportunities(command: dict, confirmed: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str, float]] = set()
    pending_entries = EntryRepository.pending()
    sources = []
    for card in command.get("cards", []):
        sources.extend(card.get("props", []))
    sources.extend(confirmed.get("props", []))
    for prop in sources:
        offer_type = str(prop.get("line_offer_type") or "").lower()
        if prop.get("adjusted_line") and not prop.get("is_discounted_line") and offer_type != "demon":
            continue
        if offer_type == "demon" or prop.get("is_premium_line"):
            original_direction = str(prop.get("direction") or "Over").strip().lower()
            prop = {**prop, "direction": "Over", "allowed_directions": ["Over"]}
            if original_direction == "under":
                if prop.get("confidence") is not None:
                    prop["confidence"] = max(0.0, min(100.0, 100.0 - float(prop["confidence"])))
                if prop.get("edge") is not None:
                    prop["edge"] = -float(prop["edge"])
        elif (
            float(prop.get("confidence") or 50.0) < 50.0
            and float(prop.get("edge") or 0.0) < 0.0
        ):
            prop = {
                **prop,
                "direction": "Under" if str(prop.get("direction") or "Over").lower() == "over" else "Over",
                "confidence": 100.0 - float(prop.get("confidence") or 50.0),
                "edge": abs(float(prop.get("edge") or 0.0)),
            }
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
        confidence = _sample_adjusted_probability(prop)
        market_supported = bool(sportsbook_odds.prop_market_key(stat))
        quality = float((prop.get("data_quality") or {}).get("score") or 50.0)
        score = max(confidence, (confidence * 0.74) + (quality * 0.18) + min(8.0, abs(float(prop.get("edge") or 0.0)) * 3.0))
        push_profile = push_risk(prop)
        score -= float(push_profile["score"]) * 0.12
        if not market_supported:
            score = min(score, 59.0)
        rows.append({
            "player": player,
            "player_identity_id": prop.get("player_identity_id"),
            "player_provider": prop.get("player_provider", ""),
            "provider_player_id": prop.get("provider_player_id", ""),
            "provider_projection_id": prop.get("provider_projection_id") or prop.get("projection_id") or "",
            "projection_id": prop.get("projection_id") or prop.get("provider_projection_id") or "",
            "team": prop.get("team", ""),
            "position": prop.get("position", ""),
            "stat": stat,
            "direction": direction,
            "line": line,
            "baseline_line": prop.get("baseline_line"),
            "standard_line": prop.get("standard_line"),
            "line_offer_type": prop.get("line_offer_type"),
            "adjusted_line": prop.get("adjusted_line", False),
            "is_discounted_line": prop.get("is_discounted_line", False),
            "is_premium_line": prop.get("is_premium_line", False),
            "line_discount": prop.get("line_discount", 0.0),
            "sport": prop.get("sport") or prop.get("league") or "",
            "league": prop.get("league") or prop.get("sport") or "",
            "platform": prop.get("platform", ""),
            "game": prop.get("game", ""),
            "game_time": prop.get("game_time", ""),
            "projection": prop.get("projection"),
            "edge": prop.get("edge", 0.0),
            "confidence": round(confidence, 1),
            "score": round(max(0.0, min(100.0, score)), 1),
            "market_supported": market_supported,
            "stars": _opportunity_stars(score),
            "data_strength": prop.get("data_strength") or _data_strength_labels(prop),
            "auto_projected": prop.get("auto_projected", False),
            "provider_backed": prop.get("provider_backed", False),
            "projection_source": prop.get("projection_source", ""),
            "model_version": prop.get("model_version", ""),
            "feature_as_of": prop.get("feature_as_of", ""),
            "forecast_snapshot": prop.get("forecast_snapshot") or {},
            "forecast_paid_eligible": bool(prop.get("forecast_paid_eligible")),
            "end_to_end_confirmed": bool(prop.get("end_to_end_confirmed")),
            "settlement_provider": prop.get("settlement_provider", ""),
            "data_quality": prop.get("data_quality") or {},
            "push_risk": push_profile,
            "decision_receipt": {},
        })
        rows[-1]["risk_profile"] = _prop_risk_profile(rows[-1])
        age = _age_minutes(rows[-1].get("feature_as_of"))
        rows[-1]["recommendation_freshness"] = {
            "status": "expired" if age is not None and age > 30 else "fresh",
            "age_minutes": round(age, 1) if age is not None else None,
            "expires_after_minutes": 30,
        }
    rows.sort(
        key=lambda row: (
            row.get("market_supported", False),
            not row.get("adjusted_line"),
            row["score"],
            row["confidence"],
        ),
        reverse=True,
    )
    top_rows = _opportunities_by_risk_lane(rows, per_lane=3)
    model_paid_enabled = _model_health_payload().get("paid_entry_mode") == "enabled"
    for row in top_rows:
        row["decision_receipt"] = _opportunity_decision_receipt(
            row,
            float(row.get("confidence") or 0.0),
            pending_entries,
        )
        row["trust"] = _trust_score_for_props([row])
        row["recommendation_eligibility"] = recommendation_eligibility(
            row,
            trust_score=float((row.get("trust") or {}).get("score") or 0.0),
            model_paid_enabled=model_paid_enabled,
        )
        row["actionable"] = row["recommendation_eligibility"]["paper_ready"]
        row["paid_actionable"] = row["recommendation_eligibility"]["paid_ready"]
        market = row["decision_receipt"].get("market_consensus") or {}
        labels = list(row.get("data_strength") or [])
        if market.get("available"):
            labels.append({
                "label": f"Market verified · {int(market.get('book_count') or 0)} books",
                "status": "verified",
            })
        if market.get("dfs_offers"):
            labels.append({"label": "Live DFS offer matched", "status": "verified"})
        row["data_strength"] = labels
    return top_rows


def _opportunities_by_risk_lane(rows: list[dict], *, per_lane: int = 3) -> list[dict]:
    """Keep one risk lane from crowding every other useful board option out."""
    lane_order = ("conservative", "balanced", "aggressive")
    limit = max(1, int(per_lane))
    selected = [
        row
        for lane in lane_order
        for row in [
            candidate for candidate in rows
            if (candidate.get("risk_profile") or {}).get("key") == lane
        ][:limit]
    ]
    if len(selected) >= 5:
        return selected
    selected_ids = {id(row) for row in selected}
    selected.extend(row for row in rows if id(row) not in selected_ids)
    return selected[:5]


def _opportunity_decision_receipt(
    prop: dict,
    confidence: float,
    pending_entries: list[dict],
) -> dict:
    movement = prop.get("line_movement") or _line_movement_payload(
        str(prop.get("player") or ""),
        str(prop.get("stat") or ""),
        str(prop.get("platform") or "PrizePicks"),
        LineHistoryRepository.get_history(
            str(prop.get("player") or ""),
            str(prop.get("stat") or ""),
            str(prop.get("platform") or "PrizePicks"),
            game=str(prop.get("game") or "") or None,
            line_offer_type=str(prop.get("line_offer_type") or "standard"),
        ),
        current_line=float(prop.get("line") or 0.0),
    )
    exposure = _prop_portfolio_exposure(prop, pending_entries)
    feature_age = _age_minutes(prop.get("feature_as_of"))
    market = sportsbook_odds.get_player_prop_consensus(
        str(prop.get("player") or ""),
        str(prop.get("stat") or ""),
        str(prop.get("sport") or prop.get("league") or ""),
        str(prop.get("game") or ""),
        float(prop.get("line") or 0.0),
        str(prop.get("direction") or "Over"),
        str(prop.get("team") or ""),
    )
    market_probability = market.get("market_probability") if market.get("available") else None
    model_market_edge = (
        round(confidence - float(market_probability), 2)
        if market_probability is not None
        else None
    )
    return {
        "status": "Research",
        "probability": round(confidence, 1),
        "probability_source": "EdgeIQ calibrated model",
        "market_probability": market_probability,
        "market_probability_note": market.get("reason", "Multi-book player odds are unavailable."),
        "market_source": market.get("source", ""),
        "market_book_count": int(market.get("book_count") or 0),
        "market_quality": market.get("quality", "unavailable"),
        "model_market_edge": model_market_edge,
        "market_consensus": market,
        "provider_payout_note": market.get("payout_note", ""),
        "projection": prop.get("projection"),
        "edge": round(float(prop.get("edge") or 0.0), 2),
        "movement": {
            "current": movement.get("current"),
            "previous": movement.get("previous"),
            "change": movement.get("change", 0.0),
            "direction": movement.get("direction", "flat"),
            "snapshots": len(movement.get("snapshots") or []),
        },
        "freshness": {
            "feature_age_minutes": feature_age,
            "label": f"Model snapshot {feature_age}m old" if feature_age is not None else "Refresh before paid use",
        },
        "portfolio_exposure": exposure,
        "valid_until": prop.get("game_time") or "Until the provider line, injury status, or matchup changes",
        "invalidation_rules": [
            "Re-analyze after any provider line or payout change.",
            "Do not use if player availability or matchup context changes.",
            "Paid use still requires positive provider-specific card EV.",
        ],
    }


def _prop_portfolio_exposure(prop: dict, pending_entries: list[dict]) -> dict:
    player_key = canonical_person_key(prop.get("player"))
    stat_key = _settlement_stat_key(prop.get("stat"))
    game_key = canonical_matchup_key(prop.get("game"))
    same_player_entries: set[int] = set()
    same_market_entries: set[int] = set()
    same_game_entries: set[int] = set()
    exposed_wager = 0.0
    for entry in pending_entries:
        entry_id = int(entry.get("id") or 0)
        matched_entry = False
        for pending_prop in entry.get("props") or []:
            pending_player = canonical_person_key(pending_prop.get("player"))
            pending_game = canonical_matchup_key(pending_prop.get("game"))
            if player_key and pending_player == player_key:
                same_player_entries.add(entry_id)
                matched_entry = True
                if _settlement_stat_key(pending_prop.get("stat")) == stat_key:
                    same_market_entries.add(entry_id)
            if game_key and pending_game == game_key:
                same_game_entries.add(entry_id)
                matched_entry = True
        if matched_entry and str(entry.get("entry_mode") or "real").lower() == "real":
            exposed_wager += float(entry.get("wager") or 0.0)
    return {
        "same_player_entries": len(same_player_entries),
        "same_market_entries": len(same_market_entries),
        "same_game_entries": len(same_game_entries),
        "real_money_exposure": round(exposed_wager, 2),
        "label": (
            f"{len(same_market_entries)} matching pending market"
            if same_market_entries
            else f"{len(same_player_entries)} pending player exposure"
            if same_player_entries
            else "No matching pending exposure"
        ),
    }


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
        teams = _teams_from_game(game, [prop])
        matchup_source = " @ ".join(teams[:2]) if len(teams) >= 2 else game
        key = (sport, canonical_matchup_key(matchup_source, EntryRepository.TEAM_ALIASES))
        groups.setdefault(key, []).append(prop)

    games: list[dict] = []
    odds_by_sport: dict[str, list[dict]] = {}
    for (sport, _game_key), game_props in groups.items():
        if len(games) >= 8:
            break
        raw_game = str(game_props[0].get("game") or "").strip()
        raw_teams = _teams_from_game(raw_game, [])
        game = (
            raw_game
            if len(raw_teams) >= 2
            else _matchup_label(raw_game, _teams_from_game(raw_game, game_props))
        )
        if sport not in odds_by_sport:
            odds_by_sport[sport] = sportsbook_odds.get_games(sport)
        sportsbook_game = sportsbook_odds.find_game_odds(game, sport, odds_by_sport[sport])
        games.append(_daily_game_card(platform, sport, game, game_props, sportsbook_game))
    games.sort(key=lambda game: (game["ai_score"], game["prop_count"]), reverse=True)
    return games[:6]


def _daily_game_card(
    platform: str,
    sport: str,
    game: str,
    props: list[dict],
    sportsbook_game: dict | None = None,
) -> dict:
    ranked = sorted(props, key=lambda prop: (float(prop.get("confidence") or prop.get("confirmed_score") or 0), float(prop.get("edge") or 0), int(prop.get("trending_count") or 0)), reverse=True)
    generated_props = [prop for prop in ranked if _generated_prop_eligible(prop)][:2]
    best_prop = ranked[0] if ranked else {}
    value_prop = max(ranked, key=lambda prop: abs(float(prop.get("edge") or 0)), default=best_prop)
    high_confidence = max(ranked, key=lambda prop: float(prop.get("confidence") or 0), default=best_prop)
    fade = min(ranked, key=lambda prop: (float(prop.get("confidence") or 0), float(prop.get("edge") or 0)), default={})
    avg_confidence = sum(float(prop.get("confidence") or 0) for prop in ranked) / len(ranked) if ranked else 0.0
    avg_edge = sum(float(prop.get("edge") or 0) for prop in ranked) / len(ranked) if ranked else 0.0
    teams = _teams_from_game(game, ranked)
    matchup_label = _matchup_label(game, teams)
    away_team = teams[0] if teams else ""
    home_team = teams[1] if len(teams) > 1 else ""
    movement = best_prop.get("line_movement") or {}
    try:
        weather_signal = openweather.weather_signal(openweather.fetch_weather_for_game(game, sport)) if sport in {"NFL", "MLB"} else None
    except Exception:
        weather_signal = None
    return {
        "game": game,
        "label": matchup_label,
        "matchup": matchup_label,
        "matchup_label": matchup_label,
        "home_team": home_team,
        "away_team": away_team,
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
        "vegas_line": sportsbook_odds.format_consensus_line(sportsbook_game),
        "vegas_line_source": sportsbook_game.get("source", "") if sportsbook_game else "",
        "sportsbook_count": sportsbook_game.get("sportsbook_count", 0) if sportsbook_game else 0,
        "ai_score": round(max(0.0, min(100.0, (avg_confidence * 0.72) + (abs(avg_edge) * 6.0) + min(12.0, len(ranked) * 1.5))), 1),
        "probability": round(max(0.0, min(100.0, avg_confidence)), 1),
        "line_movement": movement.get("label") or movement.get("direction") or "flat",
        "public_betting": "Unavailable from connected APIs",
        "weather": weather_signal.get("message") if weather_signal else ("Indoor/no weather edge" if sport not in {"NFL", "MLB"} else "No weather flag"),
        "generated_entry": {
            "props": [_daily_game_prop(prop) for prop in generated_props] if len(generated_props) >= 2 else [],
            "label": "Generate Entry" if len(generated_props) >= 2 else "Not enough verified props",
            "available": len(generated_props) >= 2,
        },
    }


def _generated_prop_eligible(prop: dict) -> bool:
    return bool(
        sportsbook_odds.prop_market_key(str(prop.get("stat") or ""))
        and prop.get("end_to_end_confirmed")
        and float(prop.get("confidence") or 0.0) >= 52.0
        and float(prop.get("edge") or 0.0) > 0.0
    )


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
        "baseline_line": prop.get("baseline_line"),
        "standard_line": prop.get("standard_line"),
        "line_offer_type": prop.get("line_offer_type"),
        "adjusted_line": prop.get("adjusted_line", False),
        "is_discounted_line": prop.get("is_discounted_line", False),
        "is_premium_line": prop.get("is_premium_line", False),
        "line_discount": prop.get("line_discount", 0.0),
        "projection": prop.get("projection"),
        "confidence": prop.get("confidence", 0),
        "edge": prop.get("edge", 0),
        "platform": prop.get("platform", ""),
        "game": prop.get("game", ""),
        "game_time": prop.get("game_time", ""),
        "trending_count": prop.get("trending_count", 0),
        "auto_projected": prop.get("auto_projected", False),
        "provider_backed": prop.get("provider_backed", False),
        "projection_source": prop.get("projection_source", ""),
        "projection_type": prop.get("projection_type", ""),
        "model_version": prop.get("model_version", ""),
        "feature_as_of": prop.get("feature_as_of", ""),
        "forecast_snapshot": prop.get("forecast_snapshot") or {},
        "forecast_paid_eligible": bool(prop.get("forecast_paid_eligible")),
        "end_to_end_confirmed": prop.get("end_to_end_confirmed", False),
        "settlement_provider": prop.get("settlement_provider", ""),
        "data_quality": prop.get("data_quality", {}),
        "data_strength": prop.get("data_strength") or _data_strength_labels(prop),
    }


def _data_strength_labels(prop: dict) -> list[dict]:
    labels: list[dict] = []
    if prop.get("end_to_end_confirmed") or _end_to_end_prop_eligibility(prop)["eligible"]:
        labels.append({"label": "End-to-end verified", "status": "good"})
    if prop.get("is_discounted_line"):
        labels.append({"label": "Discounted line", "status": "good"})
    elif prop.get("is_premium_line"):
        labels.append({"label": "Premium payout line", "status": "warning"})
    elif prop.get("adjusted_line"):
        labels.append({"label": "Adjusted payout", "status": "warning"})
    if prop.get("platform"):
        labels.append({"label": "Provider line verified", "status": "good"})
    forecast = prop.get("forecast_snapshot") or {}
    source = str(prop.get("projection_source") or forecast.get("source") or "")
    if source == "verified_history_distribution":
        labels.append({
            "label": "Historical model" if prop.get("forecast_paid_eligible") else "Historical model · paper",
            "status": "good" if prop.get("forecast_paid_eligible") else "warning",
        })
    elif source == "market_prior":
        labels.append({"label": "Market prior · paper", "status": "warning"})
    elif source:
        labels.append({"label": source.replace("_", " ").title(), "status": "info"})
    quality = prop.get("data_quality") or {}
    hit_rate = prop.get("hit_rate") or {}
    espn = prop.get("espn") or {}
    sample_size = int(hit_rate.get("sample_size") or espn.get("sample_size") or 0)
    if sample_size < 5 or quality.get("label") in {"thin data", "low reliability"}:
        labels.append({"label": "Thin history", "status": "warning"})
    elif hit_rate.get("source") == "final_stats" or sample_size:
        labels.append({"label": "Final stats verified", "status": "good"})
    return labels[:4]


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


def _daily_paper_cards(
    platform: str,
    sport_filter: str | None,
    dashboard_stats: dict,
    model_health: dict | None = None,
) -> list[dict]:
    paper = (dashboard_stats.get("entries") or {}).get("paper", {})
    pending_paper = int(paper.get("pending") or 0)
    if pending_paper:
        return [{
            "type": "paper_status",
            "title": "Paper Calibration Active",
            "summary": f"{pending_paper} paper entries are already pending.",
            "reason": "EdgeIQ skipped duplicate sample generation until the pending calibration entries settle.",
            "props": [],
            "stake": {"amount": 0.0, "unit_label": "Paper only"},
            "trust": {"score": 0, "label": "Learning"},
            "timing": {"score": 0, "label": "Pending"},
            "button_label": "View Performance",
        }]
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
    prop_pool_cache: dict[tuple[str, str], list[dict]] = {}
    analyzed_cache: dict[tuple, dict] = {}
    for target in _calibration_learning_targets(
        backtest_data,
        selected_sport,
        PredictionLedgerRepository.evidence_rows(include_legacy=False),
    ):
        suggestions = _paper_calibration_suggestions(
            payload,
            target,
            prop_pool_cache=prop_pool_cache,
            analyzed_cache=analyzed_cache,
        )
        for suggestion in suggestions:
            card = _command_suggestion_card(
                "Paper Calibration",
                target.get("reason", "Paper-only sample to strengthen model calibration."),
                suggestion,
                model_health,
            )
            signature = _entry_signature(card["suggestion"]["entry"])
            if signature in signatures:
                continue
            signatures.add(signature)
            action = _daily_action_card("paper", card, "Load Paper", target.get("reason", "Paper-only sample to improve calibration."))
            action["calibration_target"] = target
            action["entry_mode"] = "paper"
            cards.append(action)
            if len(cards) >= 2:
                return cards
    return cards


def _daily_watch_cards(platform: str, sport_filter: str | None, command: dict, confirmed: dict) -> list[dict]:
    watches: list[dict] = []
    for alert in _market_timing_alert_rows(
        platform,
        sport_filter,
        4,
        -110,
        min_confidence=0,
        min_ev=-25,
        alert_type="All",
        hide_outliers=True,
        scan_limit=12,
    ):
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
                "data_quality": alert.get("data_quality", {}),
                "data_strength": alert.get("data_strength", []),
                "auto_projected": alert.get("auto_projected", False),
                "provider_backed": alert.get("provider_backed", False),
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
    release = (
        card.get("release_status") or _card_release_status(card)
        if section in {"bet", "watch", "paper"} and card.get("props")
        else {"ok": False, "blocks": [], "warnings": []}
    )
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
        "release_status": release,
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


def _daily_loss_protection_headline(
    protection: dict,
    bet_cards: list[dict],
    paper_cards: list[dict],
    watch_cards: list[dict],
    avoid_cards: list[dict],
) -> str:
    if protection.get("active"):
        mode = str(protection.get("mode") or "watch").title()
        return f"Loss Protection {mode}: no paid card clears recovery rules yet."
    return _daily_briefing_headline(bet_cards, paper_cards, watch_cards, avoid_cards)


def _command_single_card(prop: dict, model_health: dict | None = None) -> dict:
    trust = _trust_score_for_props([prop], [])
    timing = _market_timing_score_for_props([prop])
    line_shop_summary = _line_shop_summary_for_props([prop])
    stake = _stake_recommendation_for_props([prop], trust)
    card = {
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
            trust=trust,
            timing=timing,
        ),
    }
    card["release_status"] = _card_release_status(card, model_health)
    return card


def _command_suggestion_card(title: str, summary: str, suggestion, model_health: dict | None = None) -> dict:
    serialized = _serialize_suggestion(suggestion, include_release=False)
    props = serialized["entry"]["props"]
    warnings = serialized["warnings"]
    trust = serialized["trust"]
    timing = _market_timing_score_for_props(props)
    line_shop_summary = _line_shop_summary_for_props(props)
    stake = _stake_recommendation_for_props(props, trust)
    card = {
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
            trust=trust,
            timing=timing,
        ),
    }
    card["release_status"] = _card_release_status(card, model_health)
    return card


def _recommendation_explanation(
    title: str,
    score: float,
    grade: str,
    props: list[dict],
    warnings: list[str],
    summary: str,
    trust: dict | None = None,
    timing: dict | None = None,
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
    trust = trust or _trust_score_for_props(props, warnings)
    timing = timing or _market_timing_score_for_props(props)
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
    global _TRUST_CLV_CACHE
    now = time.monotonic()
    with _TRUST_CLV_LOCK:
        if _TRUST_CLV_CACHE[0] > now:
            clv = _TRUST_CLV_CACHE[1]
        else:
            clv = clv_report()
            _TRUST_CLV_CACHE = (now + 30.0, clv)
    avg_clv = float(clv.get("average_clv") or 0.0)
    clv_penalty = min(12.0, abs(avg_clv) * 1.8) if avg_clv < 0 else 0.0
    correlation_penalty = min(18.0, len(warnings) * 6.0)
    edge_score = max(0.0, min(100.0, 52.0 + avg_edge * 8.0))
    source_score = min(100.0, 45.0 + source_count * 10.0)
    score = round(
        (avg_confidence * 0.28)
        + (edge_score * 0.22)
        + (avg_quality * 0.2)
        + (source_score * 0.14)
        + (line_score * 0.16)
        - correlation_penalty
        - clv_penalty,
        1,
    )
    score = max(0.0, min(100.0, score))
    unsupported_markets = [
        str(prop.get("stat") or "Unknown stat")
        for prop in props
        if not sportsbook_odds.prop_market_key(str(prop.get("stat") or ""))
    ]
    if unsupported_markets:
        score = min(score, 49.0)
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
    if clv_penalty:
        flags.append(f"Recent CLV is negative ({avg_clv:+.2f}).")
    if unsupported_markets:
        flags.append(f"No external sportsbook mapping for {unsupported_markets[0]}.")
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
            "clv_penalty": round(clv_penalty, 1),
        },
        "flags": flags[:4],
    }


def _best_line_edge_for_prop(prop: dict) -> float:
    direction = prop.get("direction") or "Over"
    current_line = float(prop.get("line") or 0.0)
    baseline = prop.get("standard_line") or prop.get("baseline_line")
    if not current_line or baseline in (None, ""):
        return 0.0
    standard_line = float(baseline)
    return round(standard_line - current_line, 2) if direction == "Over" else round(current_line - standard_line, 2)


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


def _prop_risk_profile(prop: dict) -> dict:
    confidence = float(prop.get("confidence") or 0.0)
    quality = float((prop.get("data_quality") or {}).get("score") or 0.0)
    forecast = prop.get("forecast_snapshot") or {}
    distribution = forecast.get("distribution") or {}
    uncertainty = str(distribution.get("uncertainty_level") or "Unknown")
    paid_eligible = bool(prop.get("forecast_paid_eligible"))
    market_supported = bool(sportsbook_odds.prop_market_key(str(prop.get("stat") or "")))
    if paid_eligible and market_supported and confidence >= 62 and quality >= 70 and uncertainty != "High":
        return {
            "key": "conservative", "label": "Conservative",
            "description": "Stronger evidence, lower uncertainty, and cleared paid-model thresholds.",
        }
    market = (prop.get("decision_receipt") or {}).get("market_consensus") or {}
    has_market_support = bool(market.get("available"))
    if market_supported and confidence >= 54 and quality >= 50 and (
        uncertainty in {"Low", "Medium"}
        or (uncertainty == "Unknown" and (has_market_support or bool(prop.get("end_to_end_confirmed"))))
    ):
        return {
            "key": "balanced", "label": "Balanced",
            "description": "Useful model edge with some uncertainty or incomplete supporting evidence.",
        }
    return {
        "key": "aggressive", "label": "Aggressive",
        "description": "Higher uncertainty, thinner evidence, or a larger outcome range. Prefer paper tracking.",
    }


def _model_health_payload() -> dict:
    global _MODEL_HEALTH_CACHE
    now = time.monotonic()
    with _MODEL_HEALTH_LOCK:
        if _MODEL_HEALTH_CACHE[0] > now:
            return dict(_MODEL_HEALTH_CACHE[1])
        payload = build_model_health_payload(ai_status())
        _MODEL_HEALTH_CACHE = (now + 30.0, dict(payload))
        return payload


def _advantage_center_payload(platform: str, sport_filter: str | None) -> dict:
    return build_advantage_center_payload(
        platform,
        sport_filter,
        command_center=lambda selected_platform, selected_sport: _command_center_payload(
            selected_platform,
            selected_sport,
            fast=True,
        ),
        clv_report=lambda: clv_report(),
        data_health=lambda: _data_health_payload(),
        personal_profile=lambda: _personal_profile_payload(),
        watchlist_alerts=lambda: _watchlist_alerts(),
        line_shop_summary=lambda props: _line_shop_summary_for_props(props),
        sportsbook_integrations=lambda: _sportsbook_integrations_payload(),
        bankroll_strategy=lambda: _bankroll_strategy(),
    )


def _sportsbook_integrations_payload() -> dict:
    bet_file = os.getenv("EDGEIQ_BET_HISTORY_FILE", "").strip()
    final_stats_file = os.getenv("EDGEIQ_FINAL_STATS_FILE", "").strip()
    odds_connected = bool(os.getenv("ODDS_API_KEY", "").strip())
    import_ready = bool(bet_file or final_stats_file)
    connected = odds_connected
    connectors = [
        {
            "name": "The Odds API",
            "status": "configured" if odds_connected else "not_configured",
            "capabilities": (
                [
                    "multi-book player prop odds",
                    "exact-line no-vig probability",
                    "PrizePicks/Underdog DFS offer evidence",
                    "quota-aware cached refresh",
                ]
                if odds_connected
                else ["game and player market odds"]
            ),
            "missing": [] if odds_connected else ["Set ODDS_API_KEY to enable live market consensus."],
        },
        {
            "name": "PrizePicks",
            "status": "manual_handoff",
            "capabilities": ["provider lines", "copy slip", "screenshot/file import", "manual result recheck"],
            "missing": ["read-only account sync", "official slip deep link"],
        },
        {
            "name": "Underdog",
            "status": "manual_handoff",
            "capabilities": ["provider lines", "copy slip", "screenshot/file import", "manual result recheck"],
            "missing": ["read-only account sync", "official slip deep link"],
        },
        {
            "name": "DraftKings Pick6",
            "status": "manual_import",
            "capabilities": ["manual entry builder", "copy slip", "screenshot/file import", "ESPN final-stat tracking"],
            "missing": ["verified live Pick6 offer feed", "provider-specific payout feed", "read-only account sync"],
        },
        {
            "name": "Local Imports",
            "status": "configured" if import_ready else "not_configured",
            "capabilities": ["CSV/JSON betting history import", "final-stat file import"] if import_ready else ["CSV/JSON upload inside Tools"],
            "missing": [] if import_ready else ["Set EDGEIQ_BET_HISTORY_FILE or EDGEIQ_FINAL_STATS_FILE for scheduled sync."],
        },
    ]
    return {
        "connected": connected,
        "market_data_connected": odds_connected,
        "import_ready": import_ready,
        "connectors": connectors,
        "headline": (
            "Multi-book market data connected; provider account handoff remains manual."
            if odds_connected
            else "Manual handoff active; multi-book market data is not connected."
        ),
        "next_step": (
            "Review exact-line book count and freshness before using market probability."
            if odds_connected
            else "Configured import files will be synced by Run Sync."
            if import_ready
            else "Use screenshot/CSV upload now; official read-only provider sync can plug into this connector layer later."
        ),
        "privacy_note": "EdgeIQ does not store sportsbook credentials or place entries automatically.",
    }


def _opportunity_feed_payload(platform: str, sport_filter: str | None, min_ev: float, limit: int, odds: int) -> dict:
    cache_key = (
        _canonical_platform(platform),
        str(sport_filter or "All Sports").strip().upper(),
        round(float(min_ev), 2),
        max(1, min(int(limit), 50)),
        int(odds),
    )
    now = time.monotonic()
    with _OPPORTUNITY_FEED_LOCK:
        expires_at, cached = _OPPORTUNITY_FEED_CACHE.get(cache_key, (0.0, {}))
        if cached and expires_at > now:
            return {
                **cached,
                "cache": {"hit": True, "ttl_seconds": OPPORTUNITY_FEED_CACHE_SECONDS},
            }
    ev_rows = _ev_scanner_rows(platform, sport_filter, min_ev=min_ev, limit=max(limit * 2, 20), odds=odds)
    timing_rows = _market_timing_alert_rows(
        platform,
        sport_filter,
        limit=max(limit, 8),
        odds=odds,
        min_ev=min_ev,
        hide_outliers=True,
        scan_limit=60,
        rows=ev_rows,
    )
    watch_rows = _watchlist_alerts()
    opportunities: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for row in ev_rows:
        opportunities.append(_opportunity_from_ev_row(row))
    for row in timing_rows:
        opportunities.append(_opportunity_from_timing_row(row))
    for row in watch_rows:
        opportunities.append(_opportunity_from_watch_row(row))

    deduped = []
    for item in opportunities:
        key = (
            canonical_person_key(item.get("player")),
            item.get("stat", "").strip().lower(),
            item.get("direction", "").strip().lower(),
            item.get("platform", "").strip().lower(),
        )
        if key in seen or not key[0]:
            continue
        seen.add(key)
        deduped.append(item)
    deduped.sort(key=lambda row: (row["priority_score"], row.get("expected_value", 0.0), row.get("confidence", 0.0)), reverse=True)
    payload = {
        "feed": {
            "id": "edgeiq-opportunity-feed-v1",
            "canonical": True,
            "purpose": "Shared recommendation source for Today, Value Tools, generators, and portfolio review.",
        },
        "as_of": iso_utc(utc_now()),
        "platform": platform,
        "sport": sport_filter or "All Sports",
        "min_ev": min_ev,
        "odds": odds,
        "count": len(deduped[: max(1, min(limit, 50))]),
        "opportunities": deduped[: max(1, min(limit, 50))],
        "summary": {
            "ev_candidates": len(ev_rows),
            "timing_alerts": len(timing_rows),
            "watchlist_hits": len(watch_rows),
        },
    }
    snapshot = ModelRehabilitationRepository.save_feed(
        {
            "feed": {
                "id": "edgeiq-opportunity-feed-v2.2.1",
                "canonical": True,
                "purpose": "Shared actionable recommendation feed.",
                "platform": platform,
                "sport": sport_filter or "All Sports",
            },
            "opportunity_feed": payload,
        },
        model_version=EDGEIQ_LOCAL_MODEL_VERSION,
    )
    payload["recommendation_snapshot_id"] = snapshot["snapshot_id"]
    payload["model_version"] = EDGEIQ_LOCAL_MODEL_VERSION
    for opportunity in payload["opportunities"]:
        opportunity["recommendation_snapshot_id"] = snapshot["snapshot_id"]
        opportunity["model_version"] = EDGEIQ_LOCAL_MODEL_VERSION
    ModelRehabilitationRepository.queue_shadow(
        payload["opportunities"],
        model_version=f"{EDGEIQ_LOCAL_MODEL_VERSION}-shadow-v2.2",
    )
    with _OPPORTUNITY_FEED_LOCK:
        _OPPORTUNITY_FEED_CACHE[cache_key] = (time.monotonic() + OPPORTUNITY_FEED_CACHE_SECONDS, payload)
    return {
        **payload,
        "cache": {"hit": False, "ttl_seconds": OPPORTUNITY_FEED_CACHE_SECONDS},
    }


def _opportunity_from_ev_row(row: dict) -> dict:
    ev = float(row.get("expected_value") or 0.0)
    confidence = float(row.get("confidence") or 0.0)
    quality = float((row.get("data_quality") or {}).get("score") or 50.0)
    priority = ev + (confidence - 50.0) * 0.55 + (quality - 50.0) * 0.15
    if row.get("is_discounted_line"):
        priority += 5.0
    if row.get("auto_projected"):
        priority -= 6.0
    return {
        "type": "Positive EV",
        "action": "Research then add to slip" if ev >= 0 else "Watch",
        "priority_score": round(priority, 1),
        "player": row.get("player", ""),
        "sport": row.get("sport", ""),
        "platform": row.get("platform", ""),
        "game": row.get("game", ""),
        "game_time": row.get("game_time", ""),
        "direction": row.get("direction", "Over"),
        "stat": row.get("stat", ""),
        "line": row.get("line"),
        "projection": row.get("projection"),
        "confidence": round(confidence, 1),
        "edge": round(float(row.get("edge") or 0.0), 2),
        "expected_value": round(ev, 2),
        "reason": row.get("probability_adjustment") or "Positive expected value versus assumed odds.",
        "data_quality": row.get("data_quality", {}),
        "data_strength": row.get("data_strength", []),
        "auto_projected": row.get("auto_projected", False),
        "provider_backed": row.get("provider_backed", False),
        "best_over": row.get("best_over"),
        "best_under": row.get("best_under"),
        "consensus_line": row.get("consensus_line"),
    }


def _opportunity_from_timing_row(row: dict) -> dict:
    priority = float(row.get("priority_score") or 0.0) + 8.0
    return {
        "type": row.get("type", "Timing"),
        "action": row.get("action", "Review timing"),
        "priority_score": round(priority, 1),
        "player": row.get("player", ""),
        "sport": row.get("sport", ""),
        "platform": row.get("platform", ""),
        "game": row.get("game", ""),
        "game_time": row.get("game_time", ""),
        "direction": row.get("direction", "Over"),
        "stat": row.get("stat", ""),
        "line": row.get("line"),
        "projection": row.get("projection"),
        "confidence": row.get("confidence", 0.0),
        "edge": row.get("edge", 0.0),
        "expected_value": row.get("expected_value", 0.0),
        "reason": row.get("reason", "Market timing alert."),
        "data_quality": row.get("data_quality", {}),
        "data_strength": row.get("data_strength", []),
        "auto_projected": row.get("auto_projected", False),
        "provider_backed": row.get("provider_backed", False),
        "movement": row.get("movement", {}),
    }


def _opportunity_from_watch_row(row: dict) -> dict:
    prop = row.get("prop") or {}
    return {
        "type": "Watchlist",
        "action": "Target reached",
        "priority_score": 62.0 + float(prop.get("confidence") or 0.0) * 0.2,
        "player": row.get("player", ""),
        "sport": prop.get("sport", ""),
        "platform": row.get("platform", ""),
        "game": prop.get("game", ""),
        "game_time": prop.get("game_time", ""),
        "direction": row.get("direction", "Over"),
        "stat": row.get("stat", ""),
        "line": row.get("line"),
        "projection": prop.get("projection"),
        "confidence": prop.get("confidence", 0.0),
        "edge": prop.get("edge", 0.0),
        "expected_value": 0.0,
        "reason": row.get("reason", "Watchlist condition matched."),
        "data_quality": prop.get("data_quality", {}),
        "data_strength": prop.get("data_strength", []),
        "auto_projected": prop.get("auto_projected", False),
        "provider_backed": prop.get("provider_backed", False),
    }


def _advantage_game_contexts(platform: str, sport_filter: str | None) -> list[dict]:
    return build_advantage_game_contexts(
        platform,
        sport_filter,
        lambda selected_platform, selected_sport: _fetch_props(selected_platform, selected_sport),
        lambda game, sport, selected_platform: _game_context_payload(game, sport, selected_platform),
    )


def _personal_profile_payload() -> dict:
    return build_personal_profile_payload(dashboard=lambda: get_dashboard())


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
    platform_props: list[tuple[Platform, list[dict]]] | None = None,
) -> list:
    ranked = []
    for platform_model, props in (platform_props if platform_props is not None else _props_by_platform(platform)):
        props = [prop for prop in props if _is_prop_on_entry_day(prop)]
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


def _value_ranked_suggestions(suggestions: list, selected_platform: str) -> list[dict]:
    rows = []
    for suggestion in suggestions:
        serialized = _serialize_suggestion(suggestion)
        payload = _entry_payload_from_serialized(serialized["entry"], selected_platform)
        value = _platform_value_check(payload)
        value_delta = float(value.get("value_delta") or 0.0)
        release = serialized.get("release_status") or {}
        serialized["platform_value"] = value
        serialized["value_adjusted_score"] = round(
            float(serialized.get("score") or 0.0)
            + min(12.0, max(-8.0, value_delta * 3.0))
            + (8.0 if release.get("ok") else 0.0),
            1,
        )
        rows.append(serialized)
    rows.sort(key=lambda row: ((row.get("release_status") or {}).get("ok", False), row.get("value_adjusted_score", 0), row.get("score", 0)), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def _entry_payload_from_serialized(entry: dict, selected_platform: str) -> EntryPayload:
    return EntryPayload.model_validate({
        "platform": selected_platform if selected_platform != "Both" else entry.get("platform") or "PrizePicks",
        "props": [
            {
                "player": prop.get("player", ""),
                "team": prop.get("team", ""),
                "position": prop.get("position", ""),
                "sport": prop.get("sport", ""),
                "stat": prop.get("stat", ""),
                "line": prop.get("line", 0),
                "baseline_line": prop.get("baseline_line"),
                "standard_line": prop.get("standard_line"),
                "line_offer_type": prop.get("line_offer_type") or "standard",
                "adjusted_line": bool(prop.get("adjusted_line")),
                "is_discounted_line": bool(prop.get("is_discounted_line")),
                "is_premium_line": bool(prop.get("is_premium_line")),
                "line_discount": float(prop.get("line_discount") or 0.0),
                "projection": prop.get("projection"),
                "direction": prop.get("direction") or "Over",
                "platform": prop.get("platform") or entry.get("platform") or selected_platform,
                "game": prop.get("game", ""),
                "game_time": prop.get("game_time", ""),
                "season_type": prop.get("season_type", ""),
                "trending_count": int(prop.get("trending_count") or 0),
            }
            for prop in entry.get("props", [])
        ],
    })


def _optimizer_obstacles(serialized: list[dict]) -> list[str]:
    if not serialized:
        return ["No 3-leg combinations matched the current filters."]
    obstacles: list[str] = []
    paid_ready = [row for row in serialized if (row.get("release_status") or {}).get("ok")]
    if not paid_ready:
        obstacles.append("No 3-leg parlay cleared paid-entry release gates.")
    first = serialized[0]
    release = first.get("release_status") or {}
    obstacles.extend((release.get("blocks") or [])[:3])
    if first.get("grade") == "F" or "Pass" in str(first.get("action") or ""):
        obstacles.append("The highest value 3-leg is still graded Pass by entry analysis.")
    value = first.get("platform_value") or {}
    if value.get("recommended_platform") and not value.get("complete_on_recommended_platform"):
        obstacles.append("The best-value platform did not match every leg in the entry.")
    portfolio = first.get("portfolio") or {}
    if portfolio.get("conflicts"):
        obstacles.append(
            f"The leading slip exceeds {len(portfolio['conflicts'])} pending portfolio concentration limit"
            f"{'s' if len(portfolio['conflicts']) != 1 else ''}; use its lower-exposure replacement when available."
        )
    return list(dict.fromkeys(obstacles))[:5]


def _mixed_risk_suggestions(raw_props: list[dict], sport: str, platform_model: Platform) -> list:
    suggestions = []
    suggestions.extend(suggest_entries(raw_props, sport, platform_model, limit=2, leg_count=2))
    for leg_count in (3, 4, 5):
        suggestions.extend(_best_suggestion_for_leg_count(raw_props, sport, platform_model, leg_count))

    for rank, suggestion in enumerate(suggestions[:5], start=1):
        suggestion.rank = rank
    return suggestions[:5]


def _crazy_six_prop_pool(raw_props: list[dict], limit: int = 16) -> list[dict]:
    ranked = sorted(
        raw_props,
        key=lambda prop: (float(prop.get("source_score") or 0.0), int(prop.get("trending_count") or 0)),
        reverse=True,
    )
    selected: list[dict] = []
    seen_players: set[str] = set()
    for prop in ranked:
        player = canonical_person_key(prop.get("player"))
        if (
            not player
            or player in seen_players
            or not _is_prop_on_entry_day(prop)
            or not _end_to_end_prop_eligibility(prop)["eligible"]
        ):
            continue
        seen_players.add(player)
        selected.append(prop)
        if len(selected) >= limit:
            break
    return selected


def _crazy_six_feed_pool(raw_props: list[dict], sport: str | None, limit: int = 60) -> list[dict]:
    ranked = sorted(raw_props, key=lambda prop: int(prop.get("trending_count") or 0), reverse=True)
    selected: list[dict] = []
    player_counts: dict[str, int] = {}
    for prop in ranked:
        prop_sport = str(prop.get("league") or prop.get("sport") or "").upper()
        player = canonical_person_key(prop.get("player"))
        if sport and prop_sport != sport:
            continue
        if (
            not player
            or player_counts.get(player, 0) >= 2
            or not _is_prop_on_entry_day(prop)
            or not _end_to_end_prop_eligibility(prop)["eligible"]
        ):
            continue
        player_counts[player] = player_counts.get(player, 0) + 1
        selected.append(prop)
        if len(selected) >= limit:
            break
    return selected


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
        props = _prefer_standard_provider_offers([
            prop for prop in _fetch_platform_props(platform_name) if _is_prop_on_entry_day(prop)
        ])
        if props:
            platforms.append((platform_model, props))
    return platforms


def _props_by_platform_from_props(platform: str, props: list[dict]) -> list[tuple[Platform, list[dict]]]:
    selected = {_canonical_platform(platform_name) for platform_name in _selected_entry_platforms(platform)}
    grouped: dict[str, list[dict]] = {}
    for prop in props:
        if not _is_prop_on_entry_day(prop):
            continue
        platform_name = _canonical_platform(prop.get("platform", platform))
        if platform_name not in selected:
            continue
        grouped.setdefault(platform_name, []).append(prop)
    return [
        (_entry_platform_from_text(platform_name), _prefer_standard_provider_offers(rows))
        for platform_name, rows in grouped.items()
        if rows
    ]


def _prefer_standard_provider_offers(props: list[dict]) -> list[dict]:
    """Use adjusted offers only when a market has no usable standard line."""
    groups: dict[tuple[str, str, str, str, str, str], list[dict]] = {}
    for prop in props:
        platform = _canonical_platform(str(prop.get("platform") or ""))
        player_key = str(prop.get("player_id") or canonical_person_key(prop.get("player")))
        groups.setdefault((
            player_key, canonical_stat_label(prop.get("stat")),
            str(prop.get("league") or prop.get("sport") or "").upper(),
            canonical_matchup_key(prop.get("game"), EntryRepository.TEAM_ALIASES),
            str(prop.get("team") or "").upper(), platform,
        ), []).append(prop)

    selected: list[dict] = []
    for group in groups.values():
        standards = [
            prop for prop in group
            if str(prop.get("line_offer_type") or _prizepicks_offer_type(prop)).lower() == "standard"
            and _offer_line_is_usable(prop)
        ]
        discounted = [
            prop for prop in group
            if str(prop.get("line_offer_type") or _prizepicks_offer_type(prop)).lower() == "goblin"
            and _offer_line_is_usable(prop)
        ]
        selected.extend(standards or discounted)
    return selected


def _offer_line_is_usable(prop: dict) -> bool:
    if prop.get("line") in (None, "") or not (prop.get("league") or prop.get("sport")) or not prop.get("stat"):
        return True
    return prop_line_plausibility(prop).valid


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
    baseline_line = float(raw.get("baseline_line") or raw.get("standard_line") or line)
    trending_count = int(raw.get("trending_count") or 0)
    raw_projection = raw.get("projection")
    auto_projected = raw_projection in (None, "")
    initial_direction = _normalize_direction(raw.get("direction") or "Over")
    forecast = forecast_prop(
        raw.get("player", ""),
        raw.get("league", ""),
        raw.get("stat", ""),
        baseline_line,
        initial_direction,
        game_time=raw.get("game_time", ""),
        team=raw.get("team", ""),
        game=raw.get("game", ""),
    )
    projection = forecast.projection if auto_projected else float(str(raw_projection))
    direction = _prop_direction(line, projection, raw.get("direction"))
    edge = calculate_directional_edge(line, projection, direction)
    probability = calculate_confidence(edge, raw.get("stat", ""), raw.get("league", ""))
    if forecast is not None:
        probability = forecast.probability
        if direction != initial_direction:
            probability = 100.0 - probability
    platform = raw.get("platform", "PrizePicks")
    projection_source = raw.get(
        "projection_source",
        forecast.source if forecast is not None else "provider_projection",
    )
    calibration = calibrate_probability(
        probability / 100.0,
        sport=str(raw.get("league") or ""),
        stat=str(raw.get("stat") or ""),
        provider=str(platform),
        direction=direction,
        projection_source=str(projection_source),
        rows=_versioned_calibration_rows(),
    )
    probability = float(calibration["probability"])
    forecast_snapshot = forecast.snapshot()
    forecast_snapshot["provider_projection"] = None if auto_projected else projection
    forecast_snapshot["calibration"] = calibration
    movement = _line_movement_payload(
        raw.get("player", ""),
        raw.get("stat", ""),
        platform,
        LineHistoryRepository.get_history(
            raw.get("player", ""),
            raw.get("stat", ""),
            platform,
            game=str(raw.get("game") or "") or None,
            line_offer_type=str(raw.get("line_offer_type") or raw.get("odds_type") or "standard"),
        ),
        current_line=baseline_line,
    )
    hit_rate = estimate_hit_rate(
        raw.get("player", ""),
        raw.get("stat", ""),
        line,
        projection,
        trending_count,
        raw.get("league", ""),
        direction=direction,
        team=raw.get("team", ""),
    )
    row = {
        "player": raw.get("player", ""),
        "player_identity_id": raw.get("player_identity_id"),
        "player_provider": raw.get("player_provider") or platform,
        "provider_player_id": raw.get("provider_player_id") or raw.get("player_id") or "",
        "team": raw.get("team", ""),
        "position": raw.get("position", ""),
        "sport": raw.get("league", ""),
        "stat": raw.get("stat", ""),
        "line": line,
        "baseline_line": baseline_line,
        "standard_line": raw.get("standard_line"),
        "line_offer_type": raw.get("line_offer_type") or raw.get("odds_type") or "standard",
        "adjusted_line": bool(raw.get("adjusted_line") or raw.get("adjusted_odds")),
        "is_discounted_line": bool(raw.get("is_discounted_line")),
        "is_premium_line": bool(raw.get("is_premium_line")),
        "line_discount": raw.get("line_discount", 0.0),
        "projection": projection,
        "direction": direction,
        "edge": round(edge, 2),
        "confidence": round(probability, 2),
        "platform": platform,
        "game": raw.get("game", ""),
        "game_time": raw.get("game_time", ""),
        "trending_count": trending_count,
        "auto_projected": auto_projected,
        "provider_backed": not auto_projected,
        "projection_source": projection_source,
        "model_version": forecast.model_version if forecast is not None else EDGEIQ_LOCAL_MODEL_VERSION,
        "feature_as_of": forecast.feature_as_of if forecast is not None else "",
        "forecast_snapshot": forecast_snapshot,
        "forecast_paid_eligible": bool(
            forecast
            and forecast.paid_eligible
            and calibration.get("paid_eligible")
        ),
        "projection_type": "auto-projected" if auto_projected else "provider-backed",
        "end_to_end_confirmed": _end_to_end_prop_eligibility(raw)["eligible"],
        "settlement_provider": "ESPN official box score",
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
    row["data_strength"] = _data_strength_labels(row)
    row["risk_profile"] = _prop_risk_profile(row)
    with suppress(Exception):
        BoardOfferRepository.attach_analysis(row)
    return row


def _confirmed_props_payload(
    platform: str,
    sport_filter: str | None,
    limit: int = 20,
    analysis_limit: int | None = None,
) -> dict:
    raw_props = _fetch_props(platform, sport_filter)
    _record_plausibility_rejections(raw_props, fallback_provider=platform)
    confirmed: list[dict] = []
    eligible = [
        raw
        for raw in raw_props
        if _is_prop_on_entry_day(raw) and _end_to_end_prop_eligibility(raw)["eligible"]
    ]
    eligible.sort(key=_confirmed_prop_prefilter_key, reverse=True)
    pool_limit = (
        max(1, int(analysis_limit))
        if analysis_limit is not None
        else max(120, min(400, max(1, limit) * 4))
    )

    for raw in eligible[:pool_limit]:
        analyzed = _analyzed_feed_prop(raw)
        candidate = _confirmed_prop_candidate(raw, analyzed)
        if candidate is None:
            continue
        confirmed.append(candidate)

    confirmed.sort(key=lambda prop: (prop["confirmed_score"], prop["confidence"], prop["edge"], prop["trending_count"]), reverse=True)
    confirmed_raw_by_id = {id(row["_raw"]): row["_raw"] for row in confirmed}
    sorted_raw = [confirmed_raw_by_id[id(row["_raw"])] for row in confirmed if id(row["_raw"]) in confirmed_raw_by_id]
    selected_sport = sport_filter or _dominant_sport(confirmed)
    slate = _confirmed_slate_summary(confirmed)
    return {
        "platform": platform,
        "sport": selected_sport or "All Sports",
        "count": len(confirmed),
        "rejected_count": max(0, len(raw_props) - len(confirmed)),
        "analyzed_count": len(raw_props),
        "slate": slate,
        "props": [{key: value for key, value in row.items() if key != "_raw"} for row in confirmed[:limit]],
        "raw_props": sorted_raw[:limit],
        "criteria": [
            "current provider row",
            "game scheduled for today",
            "named player",
            "single-game market",
            "confirmed game time",
            "official ESPN final-stat coverage",
            "line sanity check",
            "confidence, edge, hit-rate, and data-quality context",
        ],
        "end_to_end_only": True,
        "settlement_provider": "ESPN official box score",
    }


def _record_plausibility_rejections(props: list[dict], *, fallback_provider: str = "") -> int:
    rejected = []
    for prop in props:
        result = prop_line_plausibility(prop)
        if result.valid:
            continue
        rejected.append((
            prop,
            result,
            str(prop.get("platform") or prop.get("provider") or fallback_provider),
        ))
    PlausibilityRejectionRepository.record_many(rejected)
    return len(rejected)


def _confirmed_prop_prefilter_key(raw: dict) -> tuple[int, int, float, str]:
    has_game_time = int(bool(raw.get("game_time")))
    standard_offer = int(not bool(raw.get("adjusted_line") or raw.get("adjusted_odds")))
    source_score = float(raw.get("source_score") or 0.0)
    return has_game_time, standard_offer, source_score, str(raw.get("player") or "")


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
    offer_type = str(raw.get("line_offer_type") or raw.get("odds_type") or "").lower()
    if (
        raw.get("is_premium_line")
        or offer_type == "demon"
        or (raw.get("adjusted_line") and not raw.get("is_discounted_line"))
    ):
        return None
    settlement = _end_to_end_prop_eligibility(raw)
    if not settlement["eligible"]:
        return None
    payload = PropPayload.model_validate({
        "player": analyzed.get("player", ""),
        "team": analyzed.get("team", ""),
        "position": raw.get("position", ""),
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
        "model_version": analyzed.get("model_version", ""),
        "feature_as_of": analyzed.get("feature_as_of", ""),
        "forecast_snapshot": analyzed.get("forecast_snapshot") or {},
        "forecast_paid_eligible": bool(analyzed.get("forecast_paid_eligible")),
    })
    flags = _line_sanity_flags(payload)
    quality = analyzed.get("data_quality") or {}
    hit_rate = analyzed.get("hit_rate") or {}
    confirmation_flags = []
    if not analyzed.get("game_time"):
        confirmation_flags.append("missing game time")
    if flags:
        confirmation_flags.extend(flags)
    if confirmation_flags:
        return None

    history_source = str(hit_rate.get("source") or "projection_model")
    history_bonus = 10 if history_source == "final_stats" else 4 if history_source != "projection_model" else 0
    score = (
        float(quality.get("score") or 0) * 0.34
        + float(analyzed.get("confidence") or 0) * 0.42
        + min(12.0, abs(float(analyzed.get("edge") or 0)) * 4)
        + history_bonus
    )
    raw_for_entry = {
        **raw,
        "projection": analyzed.get("projection"),
        "auto_projected": bool(analyzed.get("auto_projected")),
        "projection_source": analyzed.get("projection_source") or "line_model",
        "forecast_probability": analyzed.get("confidence"),
        "forecast_direction": analyzed.get("direction") or "Over",
        "forecast_snapshot": analyzed.get("forecast_snapshot") or {},
        "direction": analyzed.get("direction") or "Over",
        "platform": analyzed.get("platform", platform),
        "hit_rate": hit_rate,
        "confirmation": True,
        "end_to_end_confirmed": True,
        "settlement_provider": settlement["provider"],
        "source_signals": [{"source": "Verified Entry Generator", "message": "Provider line, game time, and official final-stat route confirmed before entry generation."}],
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
            "end_to_end_confirmed": True,
            "settlement_provider": settlement["provider"],
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
        sport = str(prop.get("sport") or prop.get("league") or "").upper()
        if sport:
            counts[sport] = counts.get(sport, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _feed_data_quality(row: dict, movement: dict) -> dict:
    score = 50.0
    flags = []
    if row.get("auto_projected"):
        score -= 8
        flags.append("auto-projected from line/trend")
    else:
        score += 8
    if row.get("is_discounted_line"):
        score += 6
        flags.append("discounted line vs standard market")
    elif row.get("is_premium_line"):
        flags.append("premium payout line; verify payout rules")
    elif row.get("adjusted_line"):
        flags.append("adjusted payout line")
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
    standard_rows = [prop for prop in analyzed if prop.get("line_offer_type") == "standard"]
    comparison_rows = standard_rows or analyzed
    best_over = comparison_rows[0]
    best_under = max(comparison_rows, key=lambda prop: (prop["line"], prop["trending_count"]))
    consensus_rows = comparison_rows
    consensus = round(sum(prop["line"] for prop in consensus_rows) / len(consensus_rows), 2)
    projection = round(sum(prop["projection"] for prop in consensus_rows) / len(consensus_rows), 2)
    line_spread = round(best_under["line"] - best_over["line"], 2)
    best_over_market = sportsbook_odds.get_player_prop_consensus(
        player,
        stat,
        str(sport_filter or best_over.get("sport") or ""),
        str(best_over.get("game") or ""),
        float(best_over["line"]),
        "Over",
        str(best_over.get("team") or ""),
    )
    best_under_market = (
        best_over_market
        if abs(float(best_under["line"]) - float(best_over["line"])) < 0.001
        else sportsbook_odds.get_player_prop_consensus(
            player,
            stat,
            str(sport_filter or best_under.get("sport") or ""),
            str(best_under.get("game") or ""),
            float(best_under["line"]),
            "Under",
            str(best_under.get("team") or ""),
        )
    )
    manual_no_vig = _no_vig_payload(over_odds, under_odds)
    live_no_vig = (
        _market_no_vig_payload(best_over_market)
        if best_over_market.get("available")
        and abs(float(best_under["line"]) - float(best_over["line"])) < 0.001
        else None
    )
    return {
        "player": player,
        "stat": stat,
        "sport": sport_filter or "All Sports",
        "available": True,
        "message": "Standard lines are compared separately from payout-adjusted promotional lines.",
        "lines": analyzed,
        "provider_count": len({prop.get("platform") for prop in analyzed if prop.get("platform")}),
        "market_count": len(analyzed),
        "adjusted_market_count": sum(1 for prop in analyzed if prop.get("line_offer_type") != "standard"),
        "best_over": {
            "platform": best_over["platform"],
            "line": best_over["line"],
            "line_offer_type": best_over.get("line_offer_type", "standard"),
            "standard_line": best_over.get("standard_line"),
            "edge": round(projection - best_over["line"], 2),
        },
        "best_under": {
            "platform": best_under["platform"],
            "line": best_under["line"],
            "line_offer_type": best_under.get("line_offer_type", "standard"),
            "standard_line": best_under.get("standard_line"),
            "edge": round(best_under["line"] - projection, 2),
        },
        "consensus_line": consensus,
        "projection": projection,
        "line_spread": line_spread,
        "value_note": (
            f"Best standard over is {line_spread:g} points better than the highest standard line."
            if line_spread > 0
            else "All matching providers are showing the same standard line."
        ),
        "no_vig": manual_no_vig or live_no_vig,
        "no_vig_source": "Manual odds" if manual_no_vig else "The Odds API" if live_no_vig else "",
        "multi_book": {
            "best_over": best_over_market,
            "best_under": best_under_market,
        },
    }


def _alert_delivery_settings() -> dict:
    defaults = {
        "browser_enabled": True,
        "email_enabled": False,
        "email_address": "",
        "sms_enabled": False,
        "sms_number": "",
        "webhook_enabled": False,
        "webhook_url": os.getenv("EDGEIQ_ALERT_WEBHOOK_URL", ""),
        "min_priority": 65.0,
        "channels": ["browser"],
    }
    stored = _safe_json_loads(SettingsRepository.get("alert_delivery_settings", ""))
    settings = {**defaults, **stored}
    settings["channels"] = _alert_channels(settings)
    return {
        "settings": settings,
        "delivery_hooks": configured_delivery_hooks(settings),
    }


def _update_alert_delivery_settings(payload: AlertDeliveryPayload) -> dict:
    settings = payload.model_dump()
    settings["email_address"] = settings["email_address"].strip()
    settings["sms_number"] = settings["sms_number"].strip()
    settings["webhook_url"] = settings["webhook_url"].strip()
    settings["channels"] = _alert_channels(settings)
    SettingsRepository.set("alert_delivery_settings", json.dumps(settings))
    return _alert_delivery_settings()


def _alert_channels(settings: dict) -> list[str]:
    channels = []
    if settings.get("browser_enabled"):
        channels.append("browser")
    if settings.get("email_enabled") and str(settings.get("email_address") or "").strip():
        channels.append("email")
    if settings.get("sms_enabled") and str(settings.get("sms_number") or "").strip():
        channels.append("sms")
    if settings.get("webhook_enabled") and str(settings.get("webhook_url") or "").strip():
        channels.append("webhook")
    return channels


def _deliver_alert(alert: dict) -> dict:
    settings = _alert_delivery_settings().get("settings", {})
    result = deliver_configured_alert(alert, settings, sent_at=iso_utc(utc_now()), post=requests.post)
    SettingsRepository.set("last_alert_delivery", json.dumps(result))
    return result


def _deploy_readiness_payload() -> dict:
    database_url = os.getenv("DATABASE_URL", "sqlite:///edgeiq.db")
    allowed_origins = os.getenv("EDGEIQ_ALLOWED_ORIGINS", "").strip()
    configured_mode = os.getenv("EDGEIQ_DEPLOYMENT_MODE", "auto").strip().lower()
    hosted = configured_mode == "hosted" or (
        configured_mode != "local"
        and (not database_url.startswith("sqlite") or bool(allowed_origins))
    )
    mode = "hosted" if hosted else "local"
    checks = [
        _readiness_check("PWA manifest", (STATIC_DIR / "manifest.webmanifest").exists(), "Phone install metadata is present."),
        _readiness_check("Service worker", (STATIC_DIR / "sw.js").exists(), "Offline app shell support is present."),
        _readiness_check("Static asset version", bool(STATIC_ASSET_VERSION), f"Current asset version {STATIC_ASSET_VERSION}."),
        _readiness_check(
            "App database" if not hosted else "Production database",
            not hosted or not database_url.startswith("sqlite"),
            (
                "Local SQLite storage is ready. A hosted SQL database is only needed for multi-device sync."
                if not hosted
                else "Set DATABASE_URL to Postgres or another hosted SQL database."
            ),
            status="local ready" if not hosted else None,
        ),
        _readiness_check(
            "Allowed origins",
            bool(allowed_origins),
            (
                "Not required while EdgeIQ runs only on this device."
                if not hosted
                else "Set EDGEIQ_ALLOWED_ORIGINS to the hosted app domain."
            ),
            required=hosted,
            status="local only" if not hosted else None,
        ),
        _readiness_check(
            "OpenAI key",
            bool(os.getenv("OPENAI_API_KEY")),
            "Optional. Adds enhanced screenshot and language review.",
            required=False,
        ),
        _readiness_check("Final stat provider", True, "Official ESPN box scores grade every prop allowed onto the board."),
        _readiness_check(
            "Alert webhook",
            bool(os.getenv("EDGEIQ_ALERT_WEBHOOK_URL")),
            "Optional. Connect a webhook only when external alerts are wanted.",
            required=False,
        ),
    ]
    required_checks = [check for check in checks if check["required"]]
    passed = sum(1 for check in required_checks if check["ok"])
    score = round((passed / len(required_checks)) * 100, 1) if required_checks else 100.0
    ready = all(check["ok"] for check in required_checks)
    return {
        "mode": mode,
        "score": score,
        "status": f"{mode} ready" if ready else f"{mode} needs setup",
        "checks": checks,
        "next_steps": [
            check["action"]
            for check in checks
            if check["required"] and not check["ok"]
        ][:5],
    }


def _readiness_check(
    label: str,
    ok: bool,
    action: str,
    *,
    required: bool = True,
    status: str | None = None,
) -> dict:
    resolved_status = status or ("pass" if ok else "needs setup" if required else "optional")
    return {
        "label": label,
        "ok": bool(ok),
        "required": required,
        "status": resolved_status,
        "action": action,
    }


def _player_research_payload(
    player: str,
    stat: str,
    sport_filter: str | None,
    platform: str,
    line: float | None,
) -> dict:
    source_props = _cached_research_props(platform, sport_filter)
    selected_market_props = _prefer_standard_provider_offers(_matching_market_props(
        player, stat, sport_filter, platform, source_props=source_props,
    ))
    active_props = [_analyzed_feed_prop(prop) for prop in selected_market_props]
    active_props.sort(key=lambda prop: (prop.get("platform", ""), float(prop.get("line") or 0)))
    target_line = line
    if target_line is None and active_props:
        target_line = round(sum(float(prop.get("line") or 0) for prop in active_props) / len(active_props), 2)
    history = _played_history(
        player,
        stat,
        sport=sport_filter,
        limit=120,
        team=str((active_props[0] if active_props else {}).get("team") or ""),
    )
    chart_rows = []
    for row in list(reversed(history[-12:])):
        actual = float(row.get("actual") or 0)
        chart_rows.append({
            "game": row.get("game") or row.get("game_date") or "Tracked game",
            "game_date": row.get("game_date", ""),
            "actual": actual,
            "line": target_line,
            "hit": _history_hit(actual, target_line, "Over") if target_line is not None else None,
            "source": row.get("source", "final_stats"),
        })
    recommendation = max(
        active_props,
        key=lambda prop: (float(prop.get("confidence") or 0), float(prop.get("data_quality", {}).get("score") or 0), int(prop.get("trending_count") or 0)),
        default=None,
    )
    direction = str((recommendation or {}).get("direction") or "Over")
    forecast = (
        forecast_prop(
            player,
            sport_filter or str((recommendation or {}).get("sport") or ""),
            stat,
            float(target_line),
            direction,
            history=history,
            game_time=(recommendation or {}).get("game_time"),
            team=str((recommendation or {}).get("team") or ""),
            game=str((recommendation or {}).get("game") or ""),
        )
        if target_line is not None
        else None
    )
    current_opponent = _research_opponent(
        str((recommendation or {}).get("game") or ""),
        str((recommendation or {}).get("team") or ""),
    )
    splits = {
        "last_5": _history_split(history[:5], target_line),
        "last_10": _history_split(history[:10], target_line),
        "last_20": _history_split(history[:20], target_line),
        "season": _history_split(history, target_line),
        "home": _history_split([row for row in history if _game_side(row.get("game", ""), row.get("team", "")) == "home"], target_line),
        "away": _history_split([row for row in history if _game_side(row.get("game", ""), row.get("team", "")) == "away"], target_line),
        "starter": _history_split([row for row in history if row.get("starter") is True], target_line),
        "bench": _history_split([row for row in history if row.get("starter") is False], target_line),
        "opponent": _history_split([
            row for row in history
            if current_opponent and _research_opponent(str(row.get("game") or ""), str(row.get("team") or "")) == current_opponent
        ], target_line),
        "provider_lines": len(active_props),
    }
    market_lines = [
        {
            "platform": prop.get("platform", ""),
            "line": prop.get("line"),
            "direction": prop.get("direction", "Over"),
            "confidence": prop.get("confidence", 0),
            "edge": prop.get("edge", 0),
            "offer_type": prop.get("line_offer_type", "standard"),
        }
        for prop in active_props[:8]
    ]
    research = {
        "player": player,
        "stat": stat,
        "sport": sport_filter or "All Sports",
        "platform": platform,
        "line": target_line,
        "history_count": len(history),
        "splits": splits,
        "chart": chart_rows,
        "trend": _research_trend(history),
        "market_lines": market_lines,
        "active_props": active_props[:8],
        "recommendation": recommendation,
        "forecast": forecast.snapshot() if forecast else {},
        "projection_sensitivity": _projection_sensitivity(
            player, stat, sport_filter, direction, target_line, history, recommendation or {},
        ),
        "closing_lines": _research_closing_lines(active_props),
        "teammate_splits": _research_teammate_splits(history, target_line),
        "opponent": current_opponent,
        "season_assessment": _season_assessment(forecast, current_opponent),
        "best_hitting_stats": _player_stat_hit_leaderboard(
            player,
            [
                prop for prop in source_props
                if canonical_person_key(prop.get("player")) == canonical_person_key(player)
            ],
            sport_filter,
        ),
        "notes": _research_notes(active_props, history, target_line),
    }
    availability = _bounded_player_availability_payload(
        player,
        sport_filter or str((recommendation or {}).get("sport") or ""),
        str((recommendation or {}).get("team") or ""),
        str((recommendation or {}).get("game") or ""),
    )
    return persist_player_research(research, availability=availability)


def _cached_research_props(platform: str, sport_filter: str | None) -> list[dict]:
    """Read the latest known offers without turning research into a provider refresh."""
    selected = {_canonical_platform(value) for value in _selected_platforms(platform)}
    rows: list[dict] = []
    with _PROP_FETCH_LOCK:
        for cache_key, (_, cached_rows) in _PROP_FETCH_CACHE.items():
            cached_platform = cache_key.split(":", 1)[0]
            if cached_platform in selected:
                rows.extend(dict(row) for row in cached_rows)

    if not rows:
        snapshots = ModelRehabilitationRepository.snapshot_history(20)
        for snapshot in snapshots:
            payload = snapshot.get("payload") or {}
            candidates = payload.get("props") or (payload.get("opportunity_feed") or {}).get("opportunities") or []
            for candidate in candidates:
                candidate_platform = _canonical_platform(str(candidate.get("platform") or snapshot.get("platform") or ""))
                if candidate_platform in selected:
                    rows.append(dict(candidate))

    if sport_filter:
        rows = [
            row for row in rows
            if str(row.get("league") or row.get("sport") or "").upper() == sport_filter.upper()
        ]
    deduplicated: dict[tuple, dict] = {}
    for row in rows:
        key = (
            _canonical_platform(str(row.get("platform") or "")),
            str(row.get("provider_projection_id") or row.get("projection_id") or ""),
            canonical_person_key(row.get("player")),
            _stat_match_key(str(row.get("stat") or "")),
            str(row.get("line") or ""),
            str(row.get("game") or ""),
        )
        deduplicated.setdefault(key, row)
    return list(deduplicated.values())


def _player_stat_hit_leaderboard(player: str, player_props: list[dict], sport: str | None) -> list[dict]:
    return player_stat_hit_leaderboard(player, player_props, sport, history_loader=_played_history)


def _season_assessment(forecast, opponent: str) -> dict:
    if forecast is None:
        return {
            "headline": "Add an exact line to compare this player's season performance.",
            "summary": "EdgeIQ needs a line before it can calculate a side-specific probability.",
            "strength": "Not ready",
        }
    features = forecast.features
    games = int(features.get("verified_games") or 0)
    opponent_games = int(features.get("opponent_sample") or 0)
    season_average = features.get("season_average")
    opponent_average = features.get("opponent_mean")
    if opponent and opponent_games:
        comparison = (
            f"Against {opponent}, the player averaged {opponent_average:.1f} in {opponent_games} verified game"
            f"{'s' if opponent_games != 1 else ''}, compared with {season_average:.1f} across {games} season games."
        )
        caution = " This matchup sample is small, so EdgeIQ limits how much it can change the projection." if opponent_games < 4 else " The matchup sample is large enough to influence the projection, but it does not replace recent form and role data."
    else:
        comparison = f"EdgeIQ has {games} verified season games, but no reliable head-to-head sample for the current opponent."
        caution = " The projection relies more heavily on season form, recent form, role volume, and the current market line."
    return {
        "headline": f"Season-based projection: {forecast.projection:.1f}",
        "summary": comparison + caution,
        "strength": "Strong" if forecast.paid_eligible and games >= 30 else "Developing" if games >= 10 else "Thin history",
        "verified_games": games,
        "opponent_games": opponent_games,
        "season_average": season_average,
        "opponent_average": opponent_average,
        "last_10_average": features.get("last_10_average"),
        "season_start": features.get("season_start"),
        "season_end": features.get("season_end"),
    }


def _research_opponent(game: str, team: str) -> str:
    text = str(game or "").replace(" ", "").upper()
    team_key = str(team or "").replace(" ", "").upper()
    if "@" not in text or not team_key:
        return ""
    away, home = text.split("@", 1)
    return home if team_key == away else away if team_key == home else ""


def _projection_sensitivity(
    player: str,
    stat: str,
    sport: str | None,
    direction: str,
    line: float | None,
    history: list[dict],
    recommendation: dict,
) -> dict:
    if line is None:
        return {"scenarios": [], "drivers": ["Enter an exact line to calculate sensitivity."]}
    scenarios = []
    for adjustment in (-1.0, 0.0, 1.0):
        scenario_line = round(float(line) + adjustment, 2)
        scenario = forecast_prop(
            player,
            sport or str(recommendation.get("sport") or ""),
            stat,
            scenario_line,
            direction,
            history=history,
            game_time=recommendation.get("game_time"),
            team=str(recommendation.get("team") or ""),
            game=str(recommendation.get("game") or ""),
        )
        scenarios.append({"line": scenario_line, "probability": scenario.probability})
    distribution = forecast_prop(
        player,
        sport or str(recommendation.get("sport") or ""),
        stat,
        float(line),
        direction,
        history=history,
        game_time=recommendation.get("game_time"),
        team=str(recommendation.get("team") or ""),
        game=str(recommendation.get("game") or ""),
    ).distribution
    return {
        "scenarios": scenarios,
        "drivers": distribution.get("uncertainty_drivers", []),
        "injury_status": recommendation.get("injury_status") or "No verified injury adjustment loaded",
    }


def _research_closing_lines(active_props: list[dict]) -> list[dict]:
    histories = LineHistoryRepository.get_histories(active_props)
    rows = [snapshot for history in histories.values() for snapshot in history]
    rows.sort(key=lambda row: str(row.get("recorded_at") or ""), reverse=True)
    return [
        {"line": row.get("line"), "recorded_at": iso_utc(row.get("recorded_at")), "game": row.get("game", "")}
        for row in rows[:12]
    ]


def _research_teammate_splits(history: list[dict], line: float | None) -> list[dict]:
    teammates = sorted({
        str(teammate)
        for row in history
        for teammate in (row.get("teammates") or [])
        if str(teammate).strip()
    })
    rows = []
    for teammate in teammates:
        with_rows = [row for row in history if teammate in (row.get("teammates") or [])]
        without_rows = [row for row in history if teammate not in (row.get("teammates") or [])]
        if len(with_rows) < 2 or len(without_rows) < 2:
            continue
        rows.append({
            "teammate": teammate,
            "with": _history_split(with_rows, line),
            "without": _history_split(without_rows, line),
        })
    return rows[:4]


def _sharp_consensus_payload(
    player: str,
    stat: str,
    sport_filter: str | None,
    platform: str,
    over_odds: int | None,
    under_odds: int | None,
) -> dict:
    line_shop = _line_shop_payload(player, stat, sport_filter, platform, over_odds, under_odds)
    if not line_shop.get("available"):
        return {
            **line_shop,
            "available": False,
            "fair_line": None,
            "market_width": None,
            "confidence": "No active market",
            "notes": ["No matching active provider lines were found for this player/stat."],
        }
    lines = [float(row.get("line") or 0) for row in line_shop.get("lines", []) if row.get("line") is not None]
    sorted_lines = sorted(lines)
    mid = len(sorted_lines) // 2
    fair_line = (
        sorted_lines[mid]
        if len(sorted_lines) % 2
        else round((sorted_lines[mid - 1] + sorted_lines[mid]) / 2, 2)
    )
    market_width = round(max(lines) - min(lines), 2) if lines else 0.0
    platform_count = len({row.get("platform") for row in line_shop.get("lines", []) if row.get("platform")})
    confidence = "Strong" if platform_count >= 2 and market_width <= 1 else "Usable" if platform_count >= 2 else "Thin"
    notes = [
        "Consensus uses active provider lines already loaded into EdgeIQ.",
        (
            "Exact-line no-vig probability is connected through The Odds API."
            if line_shop.get("no_vig_source") == "The Odds API"
            else "No paired exact-line sportsbook probability was available for this market."
        ),
    ]
    if line_shop.get("no_vig"):
        notes.append(f"No-vig probabilities use {line_shop.get('no_vig_source') or 'the supplied odds'}.")
    return {
        **line_shop,
        "fair_line": fair_line,
        "market_width": market_width,
        "platform_count": platform_count,
        "confidence": confidence,
        "notes": notes,
    }


def _hedge_calculator_payload(payload: HedgeCalculatorPayload) -> dict:
    original_decimal = decimal_odds(payload.original_odds)
    hedge_decimal = decimal_odds(payload.hedge_odds)
    original_stake = float(payload.original_stake)
    if hedge_decimal <= 1:
        raise HTTPException(status_code=400, detail="Hedge odds must produce a valid payout.")
    full_payout = original_stake * original_decimal
    balanced_stake = full_payout / hedge_decimal
    if payload.target == "free_roll":
        hedge_stake = min(balanced_stake, original_stake)
    elif payload.target == "min_loss":
        hedge_stake = balanced_stake * 0.75
    else:
        hedge_stake = balanced_stake
    original_wins = original_stake * (original_decimal - 1) - hedge_stake
    hedge_wins = hedge_stake * (hedge_decimal - 1) - original_stake
    return {
        "target": payload.target,
        "original_odds": payload.original_odds,
        "hedge_odds": payload.hedge_odds,
        "original_stake": round(original_stake, 2),
        "hedge_stake": round(hedge_stake, 2),
        "outcomes": [
            {"label": "Original wins", "profit": round(original_wins, 2)},
            {"label": "Hedge wins", "profit": round(hedge_wins, 2)},
        ],
        "guaranteed_profit": round(min(original_wins, hedge_wins), 2),
        "note": "Balanced hedge equalizes both outcomes before platform rules, boosts, or voids.",
    }


def _middle_calculator_payload(payload: MiddleCalculatorPayload) -> dict:
    over_decimal = decimal_odds(payload.over_odds)
    under_decimal = decimal_odds(payload.under_odds)
    over_stake = float(payload.over_stake)
    under_stake = float(payload.under_stake)
    over_profit = over_stake * (over_decimal - 1)
    under_profit = under_stake * (under_decimal - 1)
    middle_available = payload.over_line < payload.under_line
    return {
        "middle_available": middle_available,
        "middle_zone": {
            "from": payload.over_line,
            "to": payload.under_line,
            "width": round(payload.under_line - payload.over_line, 2) if middle_available else 0.0,
        },
        "outcomes": [
            {"label": f"Below {payload.over_line:g}", "profit": round(under_profit - over_stake, 2)},
            {"label": "Middle hits both", "profit": round(over_profit + under_profit, 2) if middle_available else None},
            {"label": f"Above {payload.under_line:g}", "profit": round(over_profit - under_stake, 2)},
        ],
        "total_stake": round(over_stake + under_stake, 2),
        "note": "A middle exists only when the over line is lower than the under line.",
    }


def _history_hit(actual: float, line: float | None, direction: str) -> bool | None:
    if line is None:
        return None
    return actual > line if direction == "Over" else actual < line


def _history_split(rows: list[dict], line: float | None) -> dict:
    values = [float(row.get("actual") or 0) for row in rows]
    hits = [value for value in values if _history_hit(value, line, "Over")] if line is not None else []
    return {
        "sample": len(values),
        "average": round(sum(values) / len(values), 2) if values else None,
        "hit_rate": round((len(hits) / len(values)) * 100, 1) if values and line is not None else None,
    }


def _research_trend(history: list[dict]) -> dict:
    recent = [float(row.get("actual") or 0) for row in history[:5]]
    prior = [float(row.get("actual") or 0) for row in history[5:10]]
    recent_avg = sum(recent) / len(recent) if recent else 0.0
    prior_avg = sum(prior) / len(prior) if prior else recent_avg
    values = [float(row.get("actual") or 0) for row in history[:10]]
    consistency = 0.0
    if len(values) >= 2:
        avg = sum(values) / len(values)
        variance = sum((value - avg) ** 2 for value in values) / len(values)
        consistency = max(0.0, 100.0 - variance * 4.0)
    return {
        "recent_average": round(recent_avg, 2) if recent else None,
        "prior_average": round(prior_avg, 2) if prior else None,
        "delta": round(recent_avg - prior_avg, 2) if recent else 0.0,
        "consistency_score": round(min(100.0, consistency), 1),
    }


def _game_side(game: str, team: str) -> str:
    text = (game or "").replace(" ", "").upper()
    team_key = (team or "").strip().upper()
    if "@" not in text or not team_key:
        return ""
    away, home = text.split("@", 1)
    if away == team_key:
        return "away"
    if home == team_key:
        return "home"
    return ""


def _research_notes(active_props: list[dict], history: list[dict], line: float | None) -> list[str]:
    notes = []
    if active_props:
        provider_count = len({prop.get("platform") for prop in active_props if prop.get("platform")})
        notes.append(f"{provider_count} provider market{'s' if provider_count != 1 else ''} matched this prop.")
    else:
        notes.append("No active provider-backed line is currently loaded for this prop.")
    if len(history) < 10:
        notes.append("Thin final-stat history; require stronger market confirmation before paid use.")
    if line is None:
        notes.append("Enter a line to convert history into hit-rate splits.")
    return notes


def _matching_market_props(
    player: str,
    stat: str,
    sport_filter: str | None,
    platform: str,
    *,
    source_props: list[dict] | None = None,
) -> list[dict]:
    player_key = canonical_person_key(player)
    stat_key = _stat_match_key(stat)
    props = source_props if source_props is not None else _fetch_props(platform, sport_filter)
    return [
        prop for prop in props
        if canonical_person_key(prop.get("player")) == player_key
        and _stat_match_key(str(prop.get("stat", ""))) == stat_key
        and prop.get("line") is not None
    ]


def _platform_value_check(payload: EntryPayload, *, live_refresh: bool = False) -> dict:
    selected_platform = _canonical_platform(payload.platform)
    props_by_sport = {
        sport: (_fetch_props("Both", sport) if live_refresh else _cached_props("Both", sport))
        for sport in {prop.sport for prop in payload.props}
    }
    if len(payload.props) <= 1:
        legs = [
            _platform_value_for_prop(
                prop,
                selected_platform,
                props_by_sport.get(prop.sport, []),
                include_live_consensus=live_refresh,
            )
            for prop in payload.props
        ]
    else:
        with ThreadPoolExecutor(max_workers=min(3, len(payload.props))) as pool:
            legs = list(pool.map(
                lambda prop: _platform_value_for_prop(
                    prop,
                    selected_platform,
                    props_by_sport.get(prop.sport, []),
                    include_live_consensus=live_refresh,
                ),
                payload.props,
            ))
    fallback_probabilities = []
    for prop in payload.props:
        if prop.confidence is not None:
            confidence = float(prop.confidence)
        elif prop.projection is not None:
            edge = calculate_directional_edge(
                float(prop.line),
                float(prop.projection),
                _normalize_direction(prop.direction or "Over"),
            )
            confidence = calculate_confidence(edge, prop.stat, prop.sport)
        else:
            confidence = 50.0
        fallback_probabilities.append(max(0.01, min(0.99, confidence / 100.0)))
    platform_totals: dict[str, dict] = {}
    for leg in legs:
        for row in leg.get("platforms", []):
            platform = row["platform"]
            total = platform_totals.setdefault(platform, {"platform": platform, "available_legs": 0, "total_value": 0.0, "legs": []})
            total["available_legs"] += 1
            total["total_value"] += float(row.get("value_vs_selected") or 0.0)
            total["legs"].append(row)
    totals = list(platform_totals.values())
    for total in totals:
        total["total_value"] = round(total["total_value"], 2)
        total["complete_entry"] = total["available_legs"] == len(payload.props)
        probabilities = [
            max(0.01, min(0.99, float(row.get("confidence") or fallback_probabilities[index]) / 100.0))
            for index, row in enumerate(total["legs"])
        ]
        total["payout_analysis"] = payout_analysis(
            probabilities,
            total["platform"],
            payload.payout_type,
            displayed_multiplier=payload.multiplier if total["platform"] == selected_platform else None,
            exact_schedule=payload.payout_schedule if total["platform"] == selected_platform and payload.payout_schedule else None,
        )
        live_offers = [row for row in total["legs"] if row.get("live_dfs_offer")]
        exact_payout = bool(total["platform"] == selected_platform and payload.payout_schedule)
        total["payout_evidence"] = {
            "source": "exact_offer_snapshot" if exact_payout else "The Odds API" if live_offers else "official_base_schedule",
            "live_offer_legs": len(live_offers),
            "total_legs": len(payload.props),
            "selection_multipliers": [
                row.get("selection_multiplier")
                for row in live_offers
                if row.get("selection_multiplier") is not None
            ],
            "verified": exact_payout,
            "indicative": not exact_payout,
            "note": (
                "Exact provider payout table was supplied with this card."
                if exact_payout
                else "Live DFS selection multipliers are indicative. The complete card payout must still be confirmed in the provider app."
                if live_offers
                else "Expected value uses EdgeIQ's provider-specific base payout schedule."
            ),
        }
    complete = [row for row in totals if row["complete_entry"]]
    candidates = complete or totals
    best = max(
        candidates,
        key=lambda row: (
            row["complete_entry"],
            float(row.get("payout_analysis", {}).get("expected_value") or -100.0),
            row["total_value"],
            row["available_legs"],
        ),
        default=None,
    )
    selected_total = next((row for row in totals if row["platform"] == selected_platform), None)
    value_delta = round(float(best.get("total_value") or 0.0) - float((selected_total or {}).get("total_value") or 0.0), 2) if best else 0.0
    selected_ev = float((selected_total or {}).get("payout_analysis", {}).get("expected_value") or 0.0)
    best_ev = float((best or {}).get("payout_analysis", {}).get("expected_value") or 0.0)
    ev_delta = round(best_ev - selected_ev, 2)
    payout_verified = bool(best and (best.get("payout_evidence") or {}).get("verified"))
    authoritative_economics = (
        dict((best or {}).get("payout_analysis") or {})
        if best and best.get("complete_entry") and payout_verified
        else {}
    )
    positive_ev = bool(authoritative_economics and float(authoritative_economics.get("expected_value") or 0.0) > 0)
    return {
        "selected_platform": selected_platform,
        "recommended_platform": best.get("platform") if best else selected_platform,
        "recommendation": _platform_value_recommendation(selected_platform, best, value_delta, ev_delta, len(payload.props)),
        "value_delta": value_delta,
        "ev_delta": ev_delta,
        "complete_on_recommended_platform": bool(best and best.get("complete_entry")),
        "authoritative_platform": best.get("platform") if best and best.get("complete_entry") else None,
        "authoritative_economics": authoritative_economics,
        "payout_verified": payout_verified,
        "ev_status": "verified" if payout_verified else "payout_confirmation_needed",
        "positive_ev": positive_ev,
        "platforms": sorted(
            totals,
            key=lambda row: (
                row["complete_entry"],
                float(row.get("payout_analysis", {}).get("expected_value") or -100.0),
                row["total_value"],
            ),
            reverse=True,
        ),
        "legs": legs,
    }


def _platform_value_for_prop(
    prop: PropPayload,
    selected_platform: str,
    source_props: list[dict] | None = None,
    *,
    include_live_consensus: bool = True,
) -> dict:
    direction = prop.direction or "Over"
    matches = [
        _analyzed_feed_prop(row)
        for row in _matching_market_props(
            prop.player,
            prop.stat,
            prop.sport,
            "Both",
            source_props=source_props,
        )
        if _same_offer_context(row, prop)
    ]
    market = sportsbook_odds.get_player_prop_consensus(
        prop.player,
        prop.stat,
        prop.sport,
        prop.game,
        prop.line,
        direction,
        prop.team,
    ) if include_live_consensus else {"available": False, "dfs_offers": []}
    platform_rows: dict[str, list[dict]] = {}
    for row in matches:
        platform_rows.setdefault(_canonical_platform(row.get("platform", "")), []).append(row)
    selected_line = float(prop.line)
    platform_values = []
    for platform, rows in platform_rows.items():
        best = min(rows, key=lambda row: float(row.get("line") or 0.0)) if _normalize_direction(direction) == "Over" else max(rows, key=lambda row: float(row.get("line") or 0.0))
        line = float(best.get("line") or 0.0)
        value = selected_line - line if _normalize_direction(direction) == "Over" else line - selected_line
        line_market = (
            market
            if abs(selected_line - line) < 0.001
            else sportsbook_odds.get_player_prop_consensus(
                prop.player,
                prop.stat,
                prop.sport,
                prop.game,
                line,
                direction,
                prop.team,
            )
        ) if include_live_consensus else market
        dfs_offer = next(
            (
                offer for offer in line_market.get("dfs_offers", [])
                if _canonical_platform(offer.get("platform", "")) == platform
                and abs(float(offer.get("line") or 0.0) - line) < 0.001
            ),
            None,
        )
        selection = (
            (dfs_offer or {}).get("under")
            if _normalize_direction(direction) == "Under"
            else (dfs_offer or {}).get("over")
        ) or {}
        platform_values.append({
            "platform": platform,
            "line": line,
            "value_vs_selected": round(value, 2),
            "line_offer_type": best.get("line_offer_type", "standard"),
            "standard_line": best.get("standard_line"),
            "is_discounted_line": bool(best.get("is_discounted_line")),
            "is_premium_line": bool(best.get("is_premium_line")),
            "projection": best.get("projection"),
            "confidence": best.get("confidence"),
            "edge": best.get("edge"),
            "live_dfs_offer": bool(dfs_offer),
            "selection_multiplier": selection.get("multiplier"),
            "selection_price": selection.get("price"),
            "payout_source": "The Odds API" if dfs_offer else "official_base_schedule",
        })
    best_row = max(platform_values, key=lambda row: (row["value_vs_selected"], row["is_discounted_line"]), default=None)
    return {
        "player": prop.player,
        "stat": prop.stat,
        "direction": direction,
        "selected_platform": selected_platform,
        "selected_line": selected_line,
        "best_platform": best_row.get("platform") if best_row else selected_platform,
        "best_line": best_row.get("line") if best_row else selected_line,
        "best_value": best_row.get("value_vs_selected") if best_row else 0.0,
        "platforms": sorted(platform_values, key=lambda row: row["value_vs_selected"], reverse=True),
        "market_consensus": market,
    }


def _same_offer_context(row: dict, prop: PropPayload) -> bool:
    requested_game = canonical_matchup_key(prop.game)
    row_game = canonical_matchup_key(row.get("game"))
    if requested_game:
        return bool(row_game and row_game == requested_game)
    requested_team = str(prop.team or "").strip().casefold()
    row_team = str(row.get("team") or "").strip().casefold()
    if requested_team:
        return bool(row_team and row_team == requested_team)
    return False


def _platform_value_recommendation(
    selected_platform: str,
    best: dict | None,
    value_delta: float,
    ev_delta: float,
    leg_count: int,
) -> str:
    if not best:
        return "No cross-platform match found; verify manually."
    if not best.get("complete_entry"):
        return f"{best['platform']} has the best partial value, but not all {leg_count} legs were matched there."
    best_ev = float((best.get("payout_analysis") or {}).get("expected_value") or 0.0)
    if best_ev <= 0:
        return (
            f"No matched provider clears positive expected value. "
            f"{best['platform']} is least unfavorable at {best_ev:.1f}% EV; keep this entry paper-only or avoid it."
        )
    if best["platform"] == selected_platform:
        return f"{selected_platform} has the best combined line and payout value for this entry."
    return (
        f"{best['platform']} offers {value_delta:+.2f} line value and "
        f"{ev_delta:+.1f} expected-value points versus {selected_platform}."
    )


def _entry_handoff_payload(payload: EntryPayload) -> dict:
    analysis = _entry_analysis(_entry_from_payload(payload), payload)
    platform_value = _platform_value_check(payload, live_refresh=True)
    recommended_platform = platform_value.get("recommended_platform") or _canonical_platform(payload.platform)
    release_blocks = [guard["message"] for guard in analysis.get("risk_guardrails", []) if guard.get("severity") == "danger"]
    release_warnings = [guard["message"] for guard in analysis.get("risk_guardrails", []) if guard.get("severity") != "danger"]
    live_verification = _verify_handoff_live_offers(payload, recommended_platform)
    legs = live_verification["legs"]
    release = analysis.get("release_verdict") or {}
    if payload.entry_mode == "real" and not release.get("paid_allowed"):
        release_blocks.append(str((release.get("reasons") or ["This entry did not clear paid release checks."])[0]))
    if payload.entry_mode == "real" and not live_verification["all_current"]:
        release_blocks.append("One or more provider offers changed or disappeared. Refresh the card before handoff.")
    if payload.entry_mode == "real" and not platform_value.get("payout_verified"):
        release_blocks.append("Expected value is unverified until the exact provider payout is captured.")
    stale_legs = [leg for leg in legs if leg.get("freshness_status") != "fresh"]
    if payload.entry_mode == "real" and stale_legs:
        release_blocks.append("One or more recommendation forecasts are stale. Reanalyze before handoff.")
    release_blocks = list(dict.fromkeys(release_blocks))
    copy_text = _handoff_copy_text(payload, recommended_platform, legs, platform_value)
    urls = {
        "PrizePicks": "https://app.prizepicks.com/",
        "Underdog": "https://underdogfantasy.com/",
        "DraftKings Pick6": "https://sportsbook.draftkings.com/pick6",
        "Sleeper": "https://sleeper.com/",
    }
    return {
        "platform": _canonical_platform(payload.platform),
        "recommended_platform": recommended_platform,
        "open_url": urls.get(recommended_platform, urls.get(_canonical_platform(payload.platform), "")),
        "copy_text": copy_text,
        "legs": legs,
        "ready_for_handoff": not release_blocks and bool(payload.props) and live_verification["all_current"],
        "live_verification": live_verification,
        "recommendation_freshness": "refresh_required" if stale_legs else "fresh",
        "ev_status": platform_value.get("ev_status", "unverified"),
        "blocks": release_blocks,
        "warnings": release_warnings + [
            "EdgeIQ cannot place entries automatically without an official provider integration.",
            "Re-check every line in the provider app before submitting real money.",
        ],
        "platform_value": platform_value,
        "checklist": [
            "Open the recommended platform.",
            "Search each player and stat exactly as shown.",
            "Confirm direction, line, adjusted payout type, and game time.",
            "Submit only if provider lines still match and bankroll guardrails pass.",
            "Return to EdgeIQ and save the entry for tracking.",
        ],
    }


def _verify_handoff_live_offers(payload: EntryPayload, platform: str) -> dict:
    verified_at = iso_utc(utc_now())
    legs = []
    for prop in payload.props:
        requested_offer = str(prop.line_offer_type or "standard").strip().lower()
        requested_direction = _normalize_direction(prop.direction or "Over")
        candidates = [
            row for row in _matching_market_props(prop.player, prop.stat, prop.sport, platform)
            if _canonical_platform(row.get("platform", "")) == platform
            and (not prop.game or canonical_matchup_key(row.get("game"), EntryRepository.TEAM_ALIASES)
                 == canonical_matchup_key(prop.game, EntryRepository.TEAM_ALIASES))
            and str(row.get("line_offer_type") or row.get("odds_type") or "standard").strip().lower() == requested_offer
            and requested_direction in {
                _normalize_direction(direction)
                for direction in row.get("allowed_directions", ["Over", "Under"])
            }
        ]
        exact = next((row for row in candidates if abs(float(row.get("line") or 0) - float(prop.line)) < 0.001), None)
        closest = min(candidates, key=lambda row: abs(float(row.get("line") or 0) - float(prop.line)), default=None)
        status = "current" if exact else "changed" if closest else "unavailable"
        current_line = float((exact or closest or {}).get("line") or prop.line)
        leg = _handoff_leg(prop, platform)
        age = _age_minutes(prop.feature_as_of)
        leg.update({
            "offer_status": status,
            "requested_line": float(prop.line),
            "current_line": current_line if closest or exact else None,
            "verified_at": verified_at,
            "freshness_status": "unknown" if age is None else "expired" if age > 30 else "fresh",
            "blocking_reason": (
                "" if status == "current"
                else f"The live line is now {current_line:g}." if status == "changed"
                else "This exact player, game, stat, side, and offer type is no longer on the provider board."
            ),
        })
        legs.append(leg)
    return {
        "verified_at": verified_at,
        "platform": platform,
        "all_current": bool(legs) and all(leg["offer_status"] == "current" for leg in legs),
        "current": sum(leg["offer_status"] == "current" for leg in legs),
        "changed": sum(leg["offer_status"] == "changed" for leg in legs),
        "unavailable": sum(leg["offer_status"] == "unavailable" for leg in legs),
        "legs": legs,
    }


def _share_entry_payload(payload: ShareSlipPayload) -> dict:
    handoff = _entry_handoff_payload(payload)
    share_id = hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True, default=str).encode("utf-8")
        + str(time.time()).encode("utf-8")
    ).hexdigest()[:12]
    shared = {
        "id": share_id,
        "created_at": iso_utc(utc_now()),
        "platform": handoff.get("recommended_platform") or payload.platform,
        "note": payload.note.strip(),
        "entry_mode": payload.entry_mode,
        "wager": payload.wager,
        "multiplier": payload.multiplier,
        "copy_text": handoff.get("copy_text", ""),
        "legs": handoff.get("legs", []),
        "warnings": handoff.get("warnings", []),
        "blocks": handoff.get("blocks", []),
        "platform_value": handoff.get("platform_value", {}),
    }
    SettingsRepository.set(f"shared_entry_{share_id}", json.dumps(shared))
    return {
        **shared,
        "share_url": f"/share/{share_id}",
        "api_url": f"/api/share/{share_id}",
    }


def _shared_entry_payload(share_id: str) -> dict:
    raw = SettingsRepository.get(f"shared_entry_{share_id}", "")
    if not raw:
        raise HTTPException(status_code=404, detail="Shared EdgeIQ slip was not found.")
    payload = _safe_json_loads(raw)
    return {
        **payload,
        "share_url": f"/share/{share_id}",
        "api_url": f"/api/share/{share_id}",
    }


def _shared_entry_html(share_id: str) -> str:
    try:
        shared = _shared_entry_payload(share_id)
    except HTTPException:
        return """
        <!doctype html><html><head><title>EdgeIQ Slip</title><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
        <body style="font-family:system-ui;background:#060a12;color:#f6f8ff;padding:24px"><h1>Slip not found</h1><p>This EdgeIQ share link is no longer available.</p></body></html>
        """
    legs = "".join(
        f"<li><strong>{_html_escape(leg.get('player', ''))}</strong> {_html_escape(leg.get('direction', 'Over'))} {_html_escape(str(leg.get('best_line', leg.get('line', ''))))} {_html_escape(leg.get('stat', ''))}<br><small>{_html_escape(leg.get('best_platform', shared.get('platform', '')))}</small></li>"
        for leg in shared.get("legs", [])
    )
    warnings = "".join(f"<p>{_html_escape(warning)}</p>" for warning in shared.get("warnings", [])[:4])
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>EdgeIQ Shared Slip</title>
        <style>
          body {{ margin:0; font-family: Inter, system-ui, -apple-system, sans-serif; background:#060a12; color:#f6f8ff; padding:24px; }}
          main {{ max-width:720px; margin:auto; border:1px solid rgba(57,255,136,.28); border-radius:12px; padding:20px; background:#101522; }}
          h1 {{ margin:0 0 8px; }} p, small {{ color:#aeb8cc; }} li {{ margin:12px 0; padding:12px; border:1px solid rgba(255,255,255,.1); border-radius:8px; list-style:none; }}
          .pill {{ display:inline-block; padding:6px 10px; border-radius:999px; background:rgba(57,255,136,.15); color:#39ff88; font-weight:800; }}
          pre {{ white-space:pre-wrap; background:#080c16; border-radius:8px; padding:12px; color:#c9d3e8; }}
        </style>
      </head>
      <body>
        <main>
          <span class="pill">EdgeIQ Shared Slip</span>
          <h1>{_html_escape(shared.get("platform", "EdgeIQ"))} {len(shared.get("legs", []))}-Leg</h1>
          <p>{_html_escape(shared.get("note") or "Review every line in the provider app before placing.")}</p>
          <ul>{legs}</ul>
          {warnings}
          <pre>{_html_escape(shared.get("copy_text", ""))}</pre>
        </main>
      </body>
    </html>
    """


def _html_escape(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _handoff_leg(prop: PropPayload, recommended_platform: str) -> dict:
    direction = prop.direction or "Over"
    best_line = prop.line
    best_platform = prop.platform or recommended_platform
    comparison = _platform_value_for_prop(prop, _canonical_platform(prop.platform or recommended_platform))
    if comparison.get("best_platform"):
        best_platform = comparison["best_platform"]
        best_line = comparison.get("best_line", prop.line)
    best_line_value = float(best_line if best_line is not None else prop.line)
    return {
        "player": prop.player,
        "team": prop.team,
        "sport": prop.sport,
        "stat": prop.stat,
        "direction": direction,
        "line": prop.line,
        "best_platform": best_platform,
        "best_line": best_line_value,
        "projection": prop.projection,
        "game": prop.game,
        "game_time": prop.game_time,
        "line_offer_type": prop.line_offer_type,
        "standard_line": prop.standard_line,
        "adjusted_line": prop.adjusted_line,
        "value_note": (
            f"{best_platform} has the best matched line at {best_line_value:g}."
            if best_line_value != prop.line or best_platform != prop.platform
            else "Selected platform has the best matched line."
        ),
    }


def _handoff_copy_text(payload: EntryPayload, recommended_platform: str, legs: list[dict], platform_value: dict) -> str:
    header = [
        f"EdgeIQ {len(legs)}-leg handoff",
        f"Recommended app: {recommended_platform}",
        f"Entry type: {payload.entry_mode}",
        f"Wager: ${payload.wager:.2f}" if payload.entry_mode == "real" else "Wager: paper entry",
        f"Multiplier: {payload.multiplier:g}x",
        platform_value.get("recommendation", ""),
        "",
        "Legs:",
    ]
    body = [
        f"{index}. {leg['player']} {leg['direction']} {leg['line']:g} {leg['stat']} ({leg['sport']})"
        + (f" · {leg['game']}" if leg.get("game") else "")
        + (f" · {leg['line_offer_type']}" if leg.get("line_offer_type") and leg.get("line_offer_type") != "standard" else "")
        for index, leg in enumerate(legs, start=1)
    ]
    footer = ["", "Before submitting: verify every live line, player, stat label, game time, and payout in the provider app."]
    return "\n".join([line for line in header + body + footer if line is not None])


def _ev_scanner_rows(
    platform: str,
    sport_filter: str | None,
    min_ev: float,
    limit: int,
    odds: int,
) -> list[dict]:
    props = _prefer_standard_provider_offers(_fetch_props(platform, sport_filter))
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    for prop in props:
        key = _market_group_key(prop)
        if key[0] and key[1]:
            groups.setdefault(key, []).append(prop)

    rows = []
    seen: set[tuple[str, str, str, str]] = set()
    candidate_group_limit = max(40, min(240, limit * 4))
    candidate_groups = sorted(
        groups.values(),
        key=lambda group: max(
            (
                1 if prop.get("is_discounted_line") else 0,
                1 if prop.get("projection") not in (None, "") else 0,
                int(prop.get("trending_count") or 0),
            )
            for prop in group
        ),
        reverse=True,
    )[:candidate_group_limit]
    for group in candidate_groups:
        best_lines = _best_line_summary_for_group(group)
        analyzed_group = [_analyzed_feed_prop(raw) for raw in group]
        by_platform: dict[str, list[dict]] = {}
        for analyzed in analyzed_group:
            by_platform.setdefault(analyzed["platform"].strip().lower(), []).append(analyzed)
        for platform_rows in by_platform.values():
            analyzed = max(platform_rows, key=_ev_candidate_score)
            key = (
                canonical_person_key(analyzed.get("player")),
                analyzed["stat"].strip().lower(),
                analyzed["sport"].strip().upper(),
                analyzed["platform"].strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            probability = _sample_adjusted_probability(analyzed)
            ev_percent = round(expected_value(odds, probability / 100) * 100, 2)
            if ev_percent < min_ev:
                continue
            rows.append({
                **analyzed,
                "estimated_probability": round(probability, 1),
                "raw_estimated_probability": round(float(analyzed["hit_rate"]["estimated_hit_rate"]), 1),
                "probability_adjustment": _probability_adjustment_note(analyzed, probability),
                "assumed_odds": odds,
                "expected_value": ev_percent,
                "sportsbook_probability": round(sportsbook_probability(odds) * 100, 2),
                "best_over": best_lines["best_over"],
                "best_under": best_lines["best_under"],
                "consensus_line": best_lines["consensus_line"],
            })

    rows.sort(key=lambda row: (row["expected_value"], row["confidence"], row["edge"]), reverse=True)
    return rows[: max(1, min(limit, 100))]


def _ev_candidate_score(prop: dict) -> tuple[float, float, float, int]:
    offer_bonus = 4.0 if prop.get("is_discounted_line") else -3.0 if prop.get("is_premium_line") else 0.0
    return (
        float(prop.get("confidence") or 0.0) + offer_bonus,
        float(prop.get("edge") or 0.0),
        abs(float(prop.get("line_discount") or 0.0)),
        int(prop.get("trending_count") or 0),
    )


def _sample_adjusted_probability(prop: dict) -> float:
    hit_rate = prop.get("hit_rate") or {}
    observed = max(0.0, min(100.0, float(hit_rate.get("estimated_hit_rate") or prop.get("confidence") or 50.0)))
    confidence = max(0.0, min(100.0, float(prop.get("confidence") or 50.0)))
    sample_size = int(hit_rate.get("sample_size") or 0)
    prior_weight = 8 if sample_size < 10 else 4
    adjusted = ((observed * sample_size) + (confidence * prior_weight)) / max(1, sample_size + prior_weight)
    edge = abs(float(prop.get("edge") or 0.0))
    if sample_size < 5 and edge < 0.5:
        adjusted = min(adjusted, 54.0)
    elif sample_size < 8:
        adjusted = min(adjusted, 58.0)
    if not sportsbook_odds.prop_market_key(str(prop.get("stat") or "")):
        adjusted = min(adjusted, 68.0)
    return max(1.0, min(99.0, adjusted))


def _probability_adjustment_note(prop: dict, probability: float) -> str:
    hit_rate = prop.get("hit_rate") or {}
    sample_size = int(hit_rate.get("sample_size") or 0)
    raw = float(hit_rate.get("estimated_hit_rate") or probability)
    if sample_size < 5:
        return f"Thin sample adjusted from {raw:.1f}% over {sample_size} games."
    if abs(raw - probability) >= 2:
        return f"Sample-size adjusted from {raw:.1f}% to {probability:.1f}%."
    return "No material probability adjustment."


def _market_timing_alert_rows(
    platform: str,
    sport_filter: str | None,
    limit: int,
    odds: int,
    min_confidence: float = 0.0,
    min_ev: float = -25.0,
    alert_type: str = "All",
    hide_outliers: bool = False,
    scan_limit: int = 60,
    rows: list[dict] | None = None,
) -> list[dict]:
    if rows is None:
        rows = _ev_scanner_rows(platform, sport_filter, min_ev=min_ev, limit=scan_limit, odds=odds)
    alerts: list[dict] = []
    for row in rows:
        alert = _timing_alert_from_row(row)
        if alert is not None:
            alerts.append(alert)
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
    sample_size = int((row.get("hit_rate") or {}).get("sample_size") or 0)
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
        action = "Verify thin history before betting" if sample_size < 5 else "Take now if you still like the edge"
        severity = "watch" if sample_size < 5 else "urgent"
        reason = (
            f"Market moved {movement.get('direction', 'flat')} by {abs_change:.1f}, supporting the {direction.lower()} side. "
            + ("History is thin, so confirm news and line source first." if sample_size < 5 else "")
        ).strip()
    elif ev >= 8 and confidence >= 58 and abs_change < 0.5 and sample_size >= 5:
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
        "probability_adjustment": row.get("probability_adjustment", ""),
        "data_quality": row.get("data_quality", {}),
        "data_strength": row.get("data_strength", []),
        "auto_projected": row.get("auto_projected", False),
        "provider_backed": row.get("provider_backed", False),
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
        canonical_person_key(prop.get("player")),
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
    standard_lines = [prop for prop in lines if _prizepicks_offer_type(prop) == "standard"]
    consensus_source = standard_lines or lines
    consensus = round(sum(float(prop["line"]) for prop in consensus_source) / len(consensus_source), 2)
    return {
        "best_over": {
            "platform": best_over.get("platform", ""),
            "line": float(best_over["line"]),
            "line_offer_type": best_over.get("line_offer_type") or best_over.get("odds_type") or "standard",
            "standard_line": best_over.get("standard_line"),
        },
        "best_under": {
            "platform": best_under.get("platform", ""),
            "line": float(best_under["line"]),
            "line_offer_type": best_under.get("line_offer_type") or best_under.get("odds_type") or "standard",
            "standard_line": best_under.get("standard_line"),
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


def _market_no_vig_payload(market: dict) -> dict | None:
    if not market.get("available"):
        return None
    over_probability = market.get("over_probability")
    under_probability = market.get("under_probability")
    if over_probability is None or under_probability is None:
        return None
    fair_over = float(over_probability) / 100.0
    fair_under = float(under_probability) / 100.0
    return {
        "over_probability": round(float(over_probability), 2),
        "under_probability": round(float(under_probability), 2),
        "over_fair_odds": _probability_to_american(fair_over),
        "under_fair_odds": _probability_to_american(fair_under),
        "hold": market.get("average_hold"),
        "book_count": int(market.get("book_count") or 0),
        "last_update": market.get("last_update", ""),
        "stale": bool(market.get("stale")),
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


def _clv_history_key(prop: dict) -> tuple[str, str, str, str, str]:
    return (
        canonical_person_key(prop.get("player")),
        canonical_stat_label(str(prop.get("stat") or "")).strip().lower(),
        str(prop.get("platform") or "").strip(),
        canonical_matchup_key(prop.get("game")),
        str(prop.get("line_offer_type") or "standard").strip().lower(),
    )


def _entry_clv_payload(
    entry: dict,
    histories: dict[tuple[str, str, str, str, str], list[dict]] | None = None,
) -> dict:
    legs = [
        _clv_for_prop(
            prop,
            entry,
            history=histories.get(_clv_history_key(prop), []) if histories is not None else None,
            history_loaded=histories is not None,
        )
        for prop in entry.get("props", [])
    ]
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


def _entry_live_market_payload(
    entry: dict,
    histories: dict[tuple[str, str, str, str, str], list[dict]],
    *,
    now: datetime,
    freshness_minutes: int = 15,
) -> dict:
    """Use recent exact-offer snapshots for active monitoring without weakening audited CLV."""
    legs = [
        _live_line_for_prop(
            prop,
            entry,
            history=histories.get(_clv_history_key(prop), []),
            now=now,
            freshness_minutes=freshness_minutes,
        )
        for prop in entry.get("props", [])
    ]
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


def _live_line_for_prop(
    prop: dict,
    entry: dict,
    *,
    history: list[dict],
    now: datetime,
    freshness_minutes: int,
) -> dict:
    placed_line = float(prop.get("line") or 0.0)
    placed_at = _aware_datetime_value(entry.get("placed_at"))
    cutoff = now.astimezone(UTC) - timedelta(minutes=max(1, freshness_minutes))
    candidates = []
    for snapshot in history:
        recorded_at = _aware_datetime_value(snapshot.get("recorded_at"))
        if recorded_at is None or recorded_at < cutoff:
            continue
        if placed_at is not None and recorded_at < placed_at - timedelta(minutes=5):
            continue
        candidates.append((recorded_at, float(snapshot["line"])))
    candidates.sort(key=lambda item: item[0])
    current_line = candidates[-1][1] if candidates else None
    movement = current_line - placed_line if current_line is not None else None
    if movement is not None and str(prop.get("direction") or "Over").lower() == "under":
        movement *= -1
    return {
        "player": prop.get("player", ""),
        "sport": prop.get("sport", ""),
        "stat": prop.get("stat", ""),
        "platform": prop.get("platform", entry.get("platform", "")),
        "placed_line": placed_line,
        "current_line": current_line,
        "clv": round(movement, 2) if movement is not None else None,
        "beat_market": movement is not None and movement > 0,
        "reliable": current_line is not None,
        "reliability_reason": "" if current_line is not None else "no_recent_exact_offer_snapshot",
        "observed_at": candidates[-1][0].isoformat().replace("+00:00", "Z") if candidates else "",
        "note": (
            "Current line matched from a recent same-game, same-offer provider snapshot."
            if current_line is not None
            else "No recent exact provider offer matched this active leg."
        ),
    }


def _grading_report_payload(compact: bool = False) -> dict:
    pending = EntryRepository.pending()
    all_entries = EntryRepository.all()
    completed = [entry for entry in all_entries if entry.get("status") == "Settled"]
    pending_rows = [_entry_progress_payload(entry, include_market_detail=False) for entry in pending[:12]]
    if compact:
        pending_rows = [_compact_grading_pending(row) for row in pending_rows]
    displayed_completed = completed[:12]
    completed_histories = LineHistoryRepository.get_histories([
        prop
        for entry in displayed_completed
        for prop in entry.get("props", [])
    ])
    completed_evidence = SettlementAuditRepository.latest_by_entry_ids([
        int(entry["id"]) for entry in displayed_completed if entry.get("id")
    ])
    completed_rows = [
        _serialize_bet_history_entry(
            entry,
            completed_evidence.get(int(entry.get("id") or 0), {}),
            completed_histories,
        )
        for entry in displayed_completed
    ]
    unknown_legs = [
        prop
        for entry in completed
        for prop in entry.get("props", [])
        if not prop.get("final_result") and prop.get("actual") is None
    ]
    verified_legs = [
        prop
        for entry in completed
        for prop in entry.get("props", [])
        if prop.get("final_source") and prop.get("final_source") not in {"projection_estimate", "unmatched"}
    ]
    clv = clv_report()
    payload = {
        "summary": {
            "pending_entries": len(pending),
            "completed_entries": len(completed),
            "unknown_legs": len(unknown_legs),
            "verified_legs": len(verified_legs),
            "verification_rate": round((len(verified_legs) / max(1, len(verified_legs) + len(unknown_legs))) * 100, 1),
            "average_clv": clv.get("average_clv", 0.0),
            "positive_clv_rate": clv.get("positive_clv_rate", 0.0),
            "tracked_clv_legs": clv.get("tracked_legs", 0),
            "quarantined_clv_legs": clv.get("quarantined_legs", 0),
        },
        "pending": pending_rows,
        "next_actions": _grading_next_actions(len(unknown_legs), clv),
    }
    if not compact:
        payload["completed"] = completed_rows
        payload["clv"] = clv
    return payload


def _compact_grading_pending(entry: dict) -> dict:
    return {
        "id": entry.get("id"),
        "status": entry.get("tracker_status", "pending"),
        "timeline_label": entry.get("next_game_time_label", ""),
        "legs": [
            {
                "player": leg.get("player", ""),
                "status": leg.get("status", "pending"),
                "timeline_label": leg.get("timeline_label", ""),
            }
            for leg in entry.get("legs", [])
        ],
    }


def _loss_protection_payload() -> dict:
    global _LOSS_PROTECTION_CACHE
    now = time.monotonic()
    dependency_token = (
        SettingsRepository.get, get_dashboard, clv_report, EntryRepository.all,
    )
    with _LOSS_PROTECTION_LOCK:
        if _LOSS_PROTECTION_CACHE[0] > now and _LOSS_PROTECTION_CACHE[1] == dependency_token:
            return dict(_LOSS_PROTECTION_CACHE[2])
        payload = _build_loss_protection_payload()
        _LOSS_PROTECTION_CACHE = (now + 15.0, dependency_token, dict(payload))
        return payload


def _build_loss_protection_payload() -> dict:
    enabled = str(SettingsRepository.get("loss_protection_enabled", "true")).strip().lower() not in {"0", "false", "no", "off"}
    dashboard_stats = _cached_dashboard_stats()
    monthly = dashboard_stats.get("monthly_profit", {})
    current_month = monthly.get("current_month", monthly) if isinstance(monthly, dict) else monthly
    monthly_profit = _money_value(current_month if isinstance(current_month, dict) else monthly)
    roi = float(dashboard_stats.get("roi") or 0.0)
    profit = float(dashboard_stats.get("profit") or 0.0)
    clv = clv_report()
    grading = _grading_report_payload_minimal(clv)
    metrics = {
        "profit": round(profit, 2),
        "roi": round(roi, 1),
        "monthly_profit": round(monthly_profit, 2),
        "average_clv": round(float(clv.get("average_clv") or 0.0), 2),
        "positive_clv_rate": round(float(clv.get("positive_clv_rate") or 0.0), 1),
        "tracked_clv_legs": int(clv.get("tracked_legs") or 0),
        "quarantined_clv_legs": int(clv.get("quarantined_legs") or 0),
        "unknown_legs": int(grading.get("unknown_legs") or 0),
        "verified_legs": int(grading.get("verified_legs") or 0),
    }
    entry_stats = dashboard_stats.get("entries") or {}
    real_stats = entry_stats.get("real") or entry_stats
    real_wins = int(real_stats.get("wins") or 0)
    real_losses = int(real_stats.get("losses") or 0)
    real_decisions = real_wins + real_losses
    real_win_rate = (real_wins / real_decisions * 100) if real_decisions else 0.0
    recommendation = dashboard_stats.get("recommendation_accuracy") or entry_stats.get("recommendation_accuracy") or {}
    recommendation_decisions = int(recommendation.get("decisions") or 0)
    recommendation_accuracy = float(recommendation.get("accuracy") or 0.0)
    metrics.update({
        "real_win_rate": round(real_win_rate, 1),
        "real_decisions": real_decisions,
        "recommendation_accuracy": round(recommendation_accuracy, 1),
        "recommendation_decisions": recommendation_decisions,
    })
    recovery_reasons: list[str] = []
    score = 100.0
    has_performance_context = any(key in dashboard_stats for key in ("profit", "roi", "monthly_profit", "entries"))
    if not has_performance_context:
        return {
            "active": False,
            "enabled": enabled,
            "triggered": False,
            "mode": "normal" if enabled else "off",
            "score": 100.0,
            "label": "Paid Entries Enabled" if enabled else "Loss Protection Off",
            "reasons": ["Performance context is not loaded; standard placement checks still apply."] if enabled else ["Loss Protection is turned off. Standard bankroll and provider checks still apply."],
            "metrics": metrics,
            "paid_rules": _loss_protection_rules("normal" if enabled else "off"),
        }
    if monthly_profit < 0:
        recovery_reasons.append(f"Current month is negative at ${monthly_profit:.2f}.")
        score -= min(28.0, abs(monthly_profit) * 4.0)
    if roi < -5:
        recovery_reasons.append(f"Tracked ROI is {roi:.1f}%.")
        score -= min(24.0, abs(roi))
    if real_decisions >= 10 and real_win_rate < 40:
        recovery_reasons.append(f"Real-money cards are winning {real_win_rate:.1f}% across {real_decisions} decisions.")
        score -= min(32.0, (40.0 - real_win_rate) * 1.4)
    if recommendation_decisions >= 10 and recommendation_accuracy < 40:
        recovery_reasons.append(
            f"EdgeIQ recommendations are winning {recommendation_accuracy:.1f}% across {recommendation_decisions} decisions."
        )
        score -= min(28.0, (40.0 - recommendation_accuracy) * 1.2)
    performance_is_soft = profit < 0 or monthly_profit < 0 or roi < 0
    if performance_is_soft and float(clv.get("tracked_legs") or 0) >= 3 and float(clv.get("average_clv") or 0.0) < 0:
        recovery_reasons.append(f"Average CLV is {float(clv.get('average_clv') or 0.0):.2f}; lines are moving against placed slips.")
        score -= 18.0
    if performance_is_soft and float(clv.get("tracked_legs") or 0) >= 3 and float(clv.get("positive_clv_rate") or 0.0) < 45:
        recovery_reasons.append(f"Only {float(clv.get('positive_clv_rate') or 0.0):.1f}% of tracked legs beat the closing line.")
        score -= 12.0
    score = round(max(0.0, min(100.0, score)), 1)
    triggered = score < 82 or bool(recovery_reasons)
    forced = (
        (real_decisions >= 10 and (real_win_rate < 25 or roi <= -25))
        or (recommendation_decisions >= 10 and recommendation_accuracy < 30)
        or monthly_profit <= -25
    )
    active = triggered and (enabled or forced)
    reasons = list(recovery_reasons)
    if active and int(grading.get("unknown_legs") or 0) >= 3:
        reasons.append(f"{int(grading.get('unknown_legs') or 0)} legs still need verified final stats.")
    mode = "off" if not enabled else "normal"
    if active:
        mode = "lockdown" if score < 55 or monthly_profit < -5 or roi < -10 else "watch"
    if forced and not enabled:
        reasons.insert(0, "Automatic Loss Protection overrode the toggle because the tracked drawdown crossed the hard safety limit.")
    elif not enabled:
        reasons = ["Loss Protection is turned off. Standard bankroll and provider checks still apply."]
    return {
        "active": active,
        "enabled": enabled,
        "triggered": triggered,
        "forced": forced,
        "mode": mode,
        "score": score,
        "label": "Automatic Loss Protection Active" if forced and active else "Loss Protection Active" if active else "Loss Protection Off" if not enabled else "Paid Entries Enabled",
        "reasons": reasons or ["Bankroll, CLV, and final-stat tracking are inside release limits."],
        "metrics": metrics,
        "paid_rules": _loss_protection_rules(mode),
    }


def _grading_report_payload_minimal(clv: dict | None = None) -> dict:
    all_entries = EntryRepository.all()
    completed = [entry for entry in all_entries if entry.get("status") == "Settled"]
    unknown_legs = [
        prop
        for entry in completed
        for prop in entry.get("props", [])
        if not prop.get("final_result") and prop.get("actual") is None
    ]
    verified_legs = [
        prop
        for entry in completed
        for prop in entry.get("props", [])
        if prop.get("final_source") and prop.get("final_source") not in {"projection_estimate", "unmatched"}
    ]
    return {
        "unknown_legs": len(unknown_legs),
        "verified_legs": len(verified_legs),
        "average_clv": (clv or {}).get("average_clv", 0.0),
        "positive_clv_rate": (clv or {}).get("positive_clv_rate", 0.0),
    }


def _loss_protection_rules(mode: str) -> list[str]:
    if mode == "off":
        return ["Loss Protection is off; standard bankroll, provider, and exposure checks still apply."]
    if mode == "normal":
        return ["Paid entries require current provider-backed lines and passing placement checks."]
    base = [
        "Loss Protection: paid entries receive a strong warning while this mode is active.",
        "Loss Protection: paper entries remain available for testing and calibration.",
        "Loss Protection: a user-selected paid entry can still be tracked after explicit confirmation.",
    ]
    if mode == "lockdown":
        base.append("Loss Protection: EdgeIQ will not endorse a paid card until CLV and monthly ROI recover.")
    else:
        base.append("Loss Protection: review the current drawdown before overriding the warning.")
    return base


def _loss_protection_watch_cards(cards: list[dict], protection: dict) -> list[dict]:
    rows = []
    for card in cards[:2]:
        protected = {
            **card,
            "title": "Protected Paid Candidate",
            "summary": "This card would normally be considered, but Loss Protection moved it to watch.",
        }
        rows.append(_daily_action_card("watch", protected, "Review", protection["reasons"][0]))
    return rows


def _loss_protection_entry_flags(entry: Entry, payload: EntryPayload | None) -> list[dict]:
    if not payload or payload.entry_mode != "real":
        return []
    protection = _loss_protection_payload()
    if not protection["active"]:
        return []
    guards: list[dict] = [{
        "severity": "warning",
        "message": (
            "Loss Protection is active. EdgeIQ does not recommend this paid entry, but you may "
            "track it after acknowledging the warning."
        ),
    }]
    if float((protection.get("metrics") or {}).get("average_clv") or 0.0) < 0:
        guards.append({
            "severity": "warning",
            "message": "Recent CLV is negative; line-shop before placing or keep this as paper.",
        })
    return guards


def _loss_review_payload(limit: int = 10) -> dict:
    return outcome_comparison(
        EntryRepository.all(),
        limit=limit,
        clv_for_prop=lambda prop: _clv_for_prop(prop),
    )


def _loss_reasons_for_entry(entry: dict) -> list[str]:
    reasons: list[str] = []
    props = entry.get("props", [])
    clv_values = [_clv_for_prop(prop).get("clv") for prop in props]
    if any(value is not None and value < 0 for value in clv_values):
        reasons.append("Negative CLV")
    if any(not prop.get("final_result") and prop.get("actual") is None for prop in props):
        reasons.append("Unknown final stats")
    if any(float(prop.get("confidence") or 0.0) < 55 for prop in props):
        reasons.append("Low confidence leg")
    if any(str(prop.get("projection_source") or "").lower() == "auto" or prop.get("auto_projected") for prop in props):
        reasons.append("Auto-projected leg")
    games = [prop.get("game") for prop in props if prop.get("game")]
    if len(games) != len(set(games)):
        reasons.append("Same-game correlation")
    if len(props) >= 4:
        reasons.append("Too many legs")
    return reasons or ["Result variance"]


def _loss_review_next_actions(buckets: list[dict]) -> list[str]:
    reasons = {bucket["reason"] for bucket in buckets[:3]}
    actions = []
    if "Negative CLV" in reasons:
        actions.append("Require positive CLV or a better competing platform line before paid placement.")
    if "Unknown final stats" in reasons:
        actions.append("Run Recheck Final Stats before trusting calibration conclusions.")
    if "Auto-projected leg" in reasons or "Low confidence leg" in reasons:
        actions.append("Keep auto-projected and low-confidence legs in paper mode until segment ROI recovers.")
    if "Too many legs" in reasons or "Same-game correlation" in reasons:
        actions.append("Prefer singles or 2-leg slips during recovery and avoid correlated games.")
    return actions or ["Keep collecting verified results; no dominant loss pattern is visible yet."]


def _grading_next_actions(unknown_legs: int, clv: dict) -> list[str]:
    actions = []
    if unknown_legs:
        actions.append(f"Run Recheck Final Stats to clear {unknown_legs} unknown leg results.")
    if float(clv.get("average_clv") or 0.0) < 0:
        actions.append("Line value is negative; tighten timing alerts and compare platforms before placing.")
    if not actions:
        actions.append("Tracking is healthy; keep logging entries with provider-backed lines.")
    return actions


def _clv_for_prop(
    prop: dict,
    entry: dict | None = None,
    *,
    history: list[dict] | None = None,
    history_loaded: bool = False,
) -> dict:
    placed_line = float(prop.get("line") or 0)
    game = str(prop.get("game") or "").strip()
    game_time = _parse_game_time(prop.get("game_time"))
    offer_type = str(prop.get("line_offer_type") or "standard").strip().lower()
    provenance = str(prop.get("projection_source") or "").strip()
    placed_at = _aware_datetime_value((entry or {}).get("placed_at"))
    current_line = None
    reliability_reason = ""
    if not game or game_time is None:
        reliability_reason = "missing_game_context"
    elif not provenance:
        reliability_reason = "legacy_offer_metadata_missing"
    else:
        if not history_loaded:
            history = LineHistoryRepository.get_history(
                prop.get("player", ""),
                prop.get("stat", ""),
                prop.get("platform", "PrizePicks"),
                game=game,
                line_offer_type=offer_type,
            )
        history = history or []
        eligible = []
        for snapshot in history:
            recorded_at = _aware_datetime_value(snapshot.get("recorded_at"))
            if recorded_at is None or recorded_at > game_time:
                continue
            if placed_at is not None and recorded_at < placed_at - timedelta(minutes=5):
                continue
            eligible.append((recorded_at, float(snapshot["line"])))
        if eligible:
            eligible.sort(key=lambda item: item[0])
            current_line = eligible[-1][1]
        else:
            reliability_reason = "no_same_game_closing_snapshot"
    movement = (current_line - placed_line) if current_line is not None else None
    if movement is not None and str(prop.get("direction") or "Over").lower() == "under":
        movement *= -1
    clv = round(movement, 2) if movement is not None else None
    return {
        "player": prop.get("player", ""),
        "sport": prop.get("sport", ""),
        "stat": prop.get("stat", ""),
        "platform": prop.get("platform", ""),
        "placed_line": placed_line,
        "current_line": current_line,
        "clv": clv,
        "beat_market": clv is not None and clv > 0,
        "reliable": clv is not None,
        "reliability_reason": reliability_reason,
        "note": (
            "Positive CLV means the closing line moved in the selected direction."
            if clv is not None
            else "CLV excluded because a same-game, same-offer closing snapshot is unavailable."
        ),
    }


def _aware_datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _count_values(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unverified")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _check_entry_result(entry: dict, allow_estimates: bool) -> dict:
    evaluation = _evaluate_entry_result(entry, allow_estimates)
    if not evaluation["settled"]:
        EntryRepository.store_partial_leg_results(entry["id"], evaluation["legs"])
        return evaluation
    EntryRepository.settle(entry["id"], evaluation["result"], dnp_legs=evaluation["dnp_legs"], dnp_mode=_dnp_mode(), leg_results=evaluation["legs"])
    ResearchEvidenceRepository.record_outcome({**entry, "props": evaluation["legs"]})
    return evaluation


def _evaluate_entry_result(entry: dict, allow_estimates: bool) -> dict:
    legs = []
    unknown = False
    source = "actual_provider"
    dnp_legs = 0

    for prop in entry["props"]:
        final_stat = _confirmed_final_stat_for_entry(prop, entry)
        actual = final_stat.get("actual") if final_stat else None
        status = final_stat.get("status") if final_stat else ""
        leg_source = str(final_stat.get("source") if final_stat else "").strip() or "unmatched"
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
        _record_settlement_audit(
            entry,
            prop,
            final_stat,
            actual,
            leg_result,
            leg_source,
            final_status,
        )
        legs.append({**prop, "actual": actual, "result": leg_result, "source": leg_source, "final_status": final_status})

    if unknown and dnp_legs < len(legs):
        return {
            "id": entry["id"],
            "settled": False,
            "result": "Unknown",
            "source": "unavailable",
            "message": "Waiting for every leg to receive confirmed final stats.",
            "legs": legs,
            "dnp_legs": dnp_legs,
        }
    if any(leg["result"] == "Loss" for leg in legs):
        result = "Loss"
    elif dnp_legs == len(legs):
        result = "DNP"
    elif any(leg["result"] == "Push" for leg in legs):
        result = "Push"
    else:
        result = "Win"

    return {
        "id": entry["id"],
        "settled": True,
        "result": result,
        "source": source,
        "message": "Settled from estimates." if source == "projection_estimate" else "Settled from final stats.",
        "legs": legs,
        "dnp_legs": dnp_legs,
    }


def _entry_progress_payload(entry: dict, include_market_detail: bool = True) -> dict:
    legs = []
    completed = 0
    source = "unavailable"
    projected_wins = projected_losses = projected_pushes = 0
    now = utc_now().replace(tzinfo=UTC)

    for prop in entry["props"]:
        final_stat = _usable_final_stat_for_entry(prop, entry)
        actual = final_stat.get("actual") if final_stat else None
        status_value = str(final_stat.get("status") if final_stat else "").strip().lower()
        timeline_status = _leg_timeline_status(prop, actual, status_value, now)
        settlement_note = _settlement_support_note(prop, timeline_status)
        settlement_sla = _leg_settlement_sla(prop, actual, now)
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
            "settlement_note": settlement_note,
            "settlement_sla": settlement_sla,
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
        "settlement_sla": {
            "status": "escalated" if any((leg.get("settlement_sla") or {}).get("overdue") for leg in legs) else "clear",
            "overdue_legs": sum(1 for leg in legs if (leg.get("settlement_sla") or {}).get("overdue")),
        },
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
        if str(prop.get("sport", "")).upper() in {"WNBA", "NBA", "MLB", "NFL", "NHL"}
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
    placed_date = _entry_placed_date(entry)
    lookup_prop = {**prop}
    trust_sportsdataio = os.getenv("EDGEIQ_TRUST_SPORTSDATAIO_FINALS", "").strip().lower() in {"1", "true", "yes"}
    if not trust_sportsdataio:
        lookup_prop["_excluded_sources"] = ["sportsdataio"]
    if placed_date is not None:
        lookup_prop["_placed_date"] = placed_date
    final_stat = _final_stat_for_prop(lookup_prop)
    if final_stat is None:
        return None
    if str(final_stat.get("status") or "").strip().lower() not in {"played", "dnp", "live"}:
        return None

    stat_date = _parse_stat_date(final_stat.get("game_date"))
    if stat_date is not None and placed_date is not None and stat_date < placed_date:
        return None

    return final_stat


def _confirmed_final_stat_for_entry(prop: dict, entry: dict) -> dict | None:
    final_stat = _usable_final_stat_for_entry(prop, entry)
    if final_stat is None:
        return None
    if str(final_stat.get("status") or "").strip().lower() not in {"played", "dnp"}:
        return None
    return final_stat


def _preview_entry_leg_repair(entry: dict, prop: dict) -> dict:
    final_stat = _confirmed_final_stat_for_entry(prop, entry)
    current_actual = prop.get("actual")
    current_result = str(prop.get("final_result") or prop.get("result") or "Pending")
    current_source = str(prop.get("final_source") or "unmatched")
    current_status = str(prop.get("final_status") or "unknown")
    if final_stat is not None:
        proposed_status = str(final_stat.get("status") or "played").lower()
        proposed_actual = final_stat.get("actual")
        proposed_result = (
            "DNP"
            if proposed_status == "dnp"
            else _leg_result(proposed_actual, prop["line"], prop.get("direction", "Over"))
            if proposed_actual is not None
            else "Unknown"
        )
        proposed_source = str(final_stat.get("source") or "verified provider")
        will_change = any((
            current_actual != proposed_actual,
            current_result != proposed_result,
            current_source != proposed_source,
            current_status.lower() != proposed_status,
        ))
        action = "update_from_local_final" if will_change else "already_verified"
        reason = (
            "A confirmed final-stat row is already available locally and can update this leg."
            if will_change
            else "Stored settlement data already matches the confirmed final-stat row."
        )
    else:
        proposed_actual = None
        proposed_result = current_result
        proposed_source = current_source
        proposed_status = current_status
        will_change = False
        if _game_has_not_started(prop):
            action = "wait_for_final"
            reason = "The game has not started, so no settlement change is available."
        elif _automatic_final_retry_expired(prop):
            action = "refresh_provider"
            reason = "No confirmed local result matched; a provider refresh is required for another attempt."
        else:
            action = "wait_for_final"
            reason = "The final box score is not available locally yet."
    return {
        "entry_prop_id": prop.get("entry_prop_id"),
        "player": prop.get("player", ""),
        "sport": prop.get("sport", ""),
        "stat": prop.get("stat", ""),
        "line": prop.get("line"),
        "direction": prop.get("direction", "Over"),
        "game": prop.get("game", ""),
        "game_time": prop.get("game_time", ""),
        "action": action,
        "will_change": will_change,
        "reason": reason,
        "current": {
            "actual": current_actual,
            "result": current_result,
            "source": current_source,
            "status": current_status,
        },
        "proposed": {
            "actual": proposed_actual,
            "result": proposed_result,
            "source": proposed_source,
            "status": proposed_status,
            "matched_player": (final_stat or {}).get("player", ""),
            "matched_game": (final_stat or {}).get("game", ""),
            "matched_game_date": (final_stat or {}).get("game_date", ""),
        },
    }


def _entry_placed_date(entry: dict) -> date | None:
    placed_at = entry.get("placed_at")
    if isinstance(placed_at, str) and placed_at.strip():
        try:
            placed_at = datetime.fromisoformat(placed_at.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(placed_at, datetime):
        if placed_at.tzinfo is None:
            placed_at = placed_at.replace(tzinfo=UTC)
        return placed_at.astimezone(ENTRY_DAY_TIME_ZONE).date()
    if isinstance(placed_at, date):
        return placed_at
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
    if any(status == "Pending" for status in statuses):
        return "In Progress"
    if any(status == "Loss" for status in statuses):
        return "Loss"
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
    if "manual_review" in timeline_statuses:
        return "Legacy Result Unavailable"
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
        if not _supports_automatic_final_stat(prop):
            return "manual_review"
        return "final_pending"
    return "awaiting_live"


def _supports_automatic_final_stat(prop: dict) -> bool:
    return _end_to_end_prop_eligibility(prop, require_context=False)["eligible"]


def _settlement_support_note(prop: dict, timeline_status: str) -> str:
    if timeline_status != "manual_review":
        return ""
    sport = str(prop.get("sport") or "this sport").upper()
    stat = str(prop.get("stat") or "this market")
    return f"This legacy {sport} {stat} market was saved before end-to-end verification was required. It is excluded from automatic calibration."


def _leg_timeline_label(timeline_status: str) -> str:
    return {
        "scheduled": "Scheduled",
        "awaiting_live": "Awaiting live stats",
        "live": "Live",
        "final_pending": "Final stats pending",
        "manual_review": "Legacy result unavailable",
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


def _leg_settlement_sla(prop: dict, actual: float | None, now: datetime) -> dict:
    start_time = _parse_game_time(prop.get("game_time", ""))
    threshold = _sport_final_pending_hours(prop.get("sport", "")) + 2.0
    if actual is not None:
        return {"status": "settled", "overdue": False, "threshold_hours": threshold}
    if start_time is None:
        return {
            "status": "start_time_needed",
            "overdue": False,
            "threshold_hours": threshold,
            "message": "A game start time is required to monitor the final-stat SLA.",
        }
    hours_since_start = (now - start_time).total_seconds() / 3600
    overdue = hours_since_start >= threshold
    remaining = max(0.0, threshold - hours_since_start)
    return {
        "status": "overdue" if overdue else "monitoring",
        "overdue": overdue,
        "threshold_hours": threshold,
        "hours_since_start": round(max(0.0, hours_since_start), 1),
        "hours_remaining": round(remaining, 1),
        "message": (
            "Final stats are overdue. Escalate provider refresh and Recheck Final Stats."
            if overdue
            else f"Final-stat SLA has {remaining:.1f} hours remaining."
        ),
    }


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
            "manual_review": "Legacy result unavailable",
            "time_unknown": "Start time needed",
        }.get(str(timeline or ""), "Waiting for live stat data")
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
        if timeline == "manual_review":
            return "Manual"
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
                parsed = parsed.replace(tzinfo=UTC)
            dated.append((parsed.astimezone(UTC), raw))
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
        return datetime.max.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_game_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def _is_prop_on_entry_day(prop: dict, now: datetime | None = None) -> bool:
    game_time = _parse_game_time(prop.get("game_time"))
    if game_time is None:
        return False
    reference = now or utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return (
        game_time.astimezone(ENTRY_DAY_TIME_ZONE).date()
        == reference.astimezone(ENTRY_DAY_TIME_ZONE).date()
    )


def _active_line_for_player_stat(player_name: str, stat: str, platform: str) -> float | None:
    props = [
        prop for prop in _fetch_props(platform, None)
        if canonical_person_key(prop.get("player")) == canonical_person_key(player_name)
        and prop.get("stat", "").strip().lower() == stat.strip().lower()
        and prop.get("line") is not None
    ]
    if not props:
        return None
    standard = [prop for prop in props if prop.get("platform") != "PrizePicks" or _prizepicks_offer_type(prop) == "standard"]
    props = standard or props
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return float(props[0]["line"])


def _entry_from_payload(payload: EntryPayload, *, hydrate_provider: bool = True) -> Entry:
    if len(payload.props) <= 1:
        props = [_prop_from_payload(prop, payload.platform, hydrate_provider=hydrate_provider) for prop in payload.props]
    else:
        with ThreadPoolExecutor(max_workers=min(3, len(payload.props))) as pool:
            props = list(pool.map(
                lambda prop: _prop_from_payload(prop, payload.platform, hydrate_provider=hydrate_provider),
                payload.props,
            ))
    return Entry(
        platform=_entry_platform_from_text(payload.platform),
        props=props,
    )


def _placement_check(payload: EntryPayload, platform_value: dict | None = None) -> dict:
    checked_props: list[dict] = []
    warnings: list[str] = []
    blocks: list[str] = []
    current_by_platform: dict[str, list[dict]] = {}

    for index, prop in enumerate(payload.props, start=1):
        platform = _canonical_platform(payload.platform or prop.platform)
        if platform not in {"PrizePicks", "Underdog"}:
            checked_props.append(_placement_prop_row(index, prop, None, "skipped"))
            continue
        if platform not in current_by_platform:
            current_by_platform[platform] = _fetch_platform_props(platform)
        current = _hydrate_payload_prop_context(prop, platform, current_by_platform[platform])
        row_status = "schedule_context" if current and current.get("context_source") == "espn_schedule" else "matched" if current else "missing"
        row = _placement_prop_row(index, prop, current, row_status)
        checked_props.append(row)

        label = f"{prop.player} {prop.direction or 'Over'} {prop.stat} {prop.line}"
        market_issue = _provider_market_issue(prop, platform, current_by_platform[platform], current)
        if market_issue:
            if _requires_verified_settlement(payload):
                blocks.append(market_issue)
            else:
                warnings.append(market_issue)
        settlement = _end_to_end_payload_eligibility(prop, payload.platform, current)
        if not settlement["eligible"]:
            message = f"{label}: {settlement['reasons'][0]}."
            if _requires_verified_settlement(payload):
                blocks.append(message)
            else:
                warnings.append(
                    f"{message} This entry can be saved, but this leg requires manual final-stat verification "
                    "and will not count as a verified model result."
                )
        if _is_season_long_prop(prop):
            message = f"{label}: season-long markets cannot use daily automatic settlement."
            if _requires_verified_settlement(payload):
                blocks.append(message)
            else:
                warnings.append(f"{message} Manual final-stat verification will be required.")
        if current is None:
            continue
        if current.get("context_source") == "espn_schedule":
            warnings.append(
                f"{label}: the game has started and the sportsbook removed its active market. "
                "EdgeIQ retained the original provider line and matched the official ESPN schedule for settlement."
            )
        current_time = str(current.get("game_time") or "").strip()
        current_line = current.get("line")
        if not current_time:
            warnings.append(f"{label}: game time is unavailable from {platform}.")
        elif not prop.game_time:
            warnings.append(f"{label}: game time confirmed as {_short_time_label(current_time)} but was missing from the slip.")
        elif str(prop.game_time).strip() != current_time:
            warnings.append(f"{label}: game time differs from current {platform} feed ({_short_time_label(current_time)}).")
        for flag in _line_sanity_flags(prop):
            warnings.append(f"{label}: {flag}")

    platform_value = platform_value or _platform_value_check(payload)
    entry = _entry_from_payload(payload)
    if payload.entry_mode == "real":
        unproven_legs = [prop for prop in entry.props if not prop.forecast_paid_eligible]
        if unproven_legs:
            message = (
                f"{len(unproven_legs)} leg{'s' if len(unproven_legs) != 1 else ''} lack enough "
                "versioned forecast and segment-calibration evidence."
            )
            blocks.append(f"{message} EdgeIQ cannot release this as a paid entry.")
        economics = platform_value.get("authoritative_economics") or {}
        if not platform_value.get("complete_on_recommended_platform"):
            blocks.append("Every paid leg must match one current provider board before placement.")
        elif float(economics.get("expected_value") or 0.0) <= 0:
            blocks.append(
                f"Best matched provider expected value is {float(economics.get('expected_value') or 0.0):.1f}%. "
                "Paid entries require positive provider-specific expected value."
            )
    loss_protection = _loss_protection_payload()
    protection_flags = _loss_protection_entry_flags(entry, payload)
    for protection_flag in protection_flags:
        detail = str(protection_flag.get("message") or "").strip()
        if not detail:
            continue
        if protection_flag.get("severity") == "danger":
            blocks.append(detail)
        else:
            warnings.append(detail)
    audit = _placement_audit_payload(payload, checked_props, warnings, blocks, platform_value, loss_protection)
    audit_blocks = [
        f"{item['label']}: {item['detail']}"
        for item in audit.get("items", [])
        if item.get("status") == "block"
    ]
    all_blocks = blocks + audit_blocks
    tracking_blocks = _generated_entry_day_blocks(payload)
    if _requires_verified_settlement(payload):
        tracking_blocks.extend(_end_to_end_placement_blocks(payload))
    return {
        "ok": not all_blocks,
        "tracking_override_allowed": payload.entry_mode == "real" and not tracking_blocks,
        "tracking_blocks": tracking_blocks,
        "requires_confirmation": bool(warnings or all_blocks),
        "warnings": warnings,
        "blocks": all_blocks,
        "props": checked_props,
        "provider_rows": sum(len(rows) for rows in current_by_platform.values()),
        "platform_value": platform_value,
        "loss_protection": loss_protection,
        "audit": audit,
    }


def _end_to_end_payload_eligibility(
    prop: PropPayload,
    entry_platform: str,
    provider_context: dict | None = None,
) -> dict:
    context = provider_context
    if context is None:
        context = _provider_context_for_payload_prop(prop, entry_platform)
    merged = {**prop.model_dump()}
    for key in ("team", "position", "sport", "league", "stat", "game", "game_time"):
        if not merged.get(key) and context.get(key):
            merged[key] = context[key]
    return _end_to_end_prop_eligibility(merged)


def _end_to_end_placement_blocks(payload: EntryPayload) -> list[str]:
    blocks: list[str] = []
    current_by_platform: dict[str, list[dict]] = {}
    requires_verified = _requires_verified_settlement(payload)
    for prop in payload.props:
        platform = _canonical_platform(payload.platform or prop.platform)
        current = None
        if requires_verified and platform in {"PrizePicks", "Underdog"}:
            if platform not in current_by_platform:
                current_by_platform[platform] = _fetch_platform_props(platform)
            current = _hydrate_payload_prop_context(prop, platform, current_by_platform[platform])
            market_issue = _provider_market_issue(prop, platform, current_by_platform[platform], current)
            if market_issue:
                blocks.append(market_issue)
        eligibility = _end_to_end_payload_eligibility(
            prop,
            payload.platform,
            provider_context=current or {},
        )
        if eligibility["eligible"]:
            continue
        label = f"{prop.player} {prop.stat}"
        blocks.append(f"{label}: {eligibility['reasons'][0]}")
    return blocks


def _requires_verified_settlement(payload: EntryPayload) -> bool:
    return payload.entry_mode == "real" and payload.recommended_by_app


def _generated_entry_day_blocks(payload: EntryPayload) -> list[str]:
    if not payload.recommended_by_app:
        return []
    outside_today = [
        f"{prop.player} {prop.stat}"
        for prop in payload.props
        if not _is_prop_on_entry_day({"game_time": prop.game_time})
    ]
    if not outside_today:
        return []
    preview = ", ".join(outside_today[:3])
    return [
        f"This generated entry is no longer on today's slate ({preview}). "
        "Refresh recommendations and build a card using games scheduled today."
    ]


def _placement_audit_payload(
    payload: EntryPayload,
    checked_props: list[dict],
    warnings: list[str],
    blocks: list[str],
    platform_value: dict,
    loss_protection: dict | None = None,
) -> dict:
    bankroll = float(get_dashboard().get("bankroll") or get_starting_bankroll() or 0)
    strategy = _bankroll_strategy()
    wager = 0.0 if payload.entry_mode == "paper" else float(payload.wager or 0.0)
    open_exposure = _open_real_money_exposure()
    exposure_cap = bankroll * float(strategy["max_open_exposure_pct"]) / 100 if bankroll else 0.0
    projected_exposure = open_exposure + wager
    matched = sum(
        1
        for row in checked_props
        if row.get("status") in {"matched", "schedule_context", "skipped"}
    )
    total = len(checked_props)
    loss_protection = loss_protection or _loss_protection_payload()
    protection_active = bool(loss_protection.get("active"))
    items = [
        {
            "label": "Provider lines",
            "status": "block" if blocks else "review" if warnings else "pass",
            "detail": f"{matched}/{total} legs matched or skipped with current provider context.",
        },
        {
            "label": "Best app value",
            "status": "pass" if platform_value.get("recommended_platform") == _canonical_platform(payload.platform) else "review",
            "detail": platform_value.get("recommendation") or "No cross-platform value recommendation.",
        },
        {
            "label": "Open exposure",
            "status": "pass" if not exposure_cap or projected_exposure <= exposure_cap else "block",
            "detail": f"{projected_exposure:.2f} projected open exposure of {exposure_cap:.2f} cap.",
        },
        {
            "label": "Entry mode",
            "status": "paper" if payload.entry_mode == "paper" else "pass" if wager > 0 else "block",
            "detail": "Paper entry will not affect bankroll." if payload.entry_mode == "paper" else f"{wager:.2f} real-money wager.",
        },
        {
            "label": "Loss protection",
            "status": "paper" if payload.entry_mode == "paper" else "review" if protection_active else "pass",
            "detail": (loss_protection.get("reasons") or ["Paid-entry recovery checks are clear."])[0],
        },
    ]
    if blocks or any(item["status"] == "block" for item in items):
        status = "blocked"
        score = 35
    elif warnings or any(item["status"] == "review" for item in items):
        status = "review"
        score = 68
    else:
        status = "clear"
        score = 92
    return {
        "status": status,
        "score": score,
        "items": items,
        "bankroll": bankroll,
        "wager": wager,
        "open_exposure": open_exposure,
        "projected_exposure": round(projected_exposure, 2),
        "open_exposure_cap": round(exposure_cap, 2),
        "recommended_platform": platform_value.get("recommended_platform") or _canonical_platform(payload.platform),
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
    stat_key = _stat_match_key(prop.stat)
    sport = prop.sport.upper()
    team = _match_key(prop.team)
    provider_player_id = str(prop.provider_player_id or "").strip()
    candidates = [
        current for current in current_props
        if (
            (provider_player_id and str(current.get("player_id") or "").strip() == provider_player_id)
            or _match_key(str(current.get("player", ""))) == player_key
        )
        and _stat_match_key(str(current.get("stat", ""))) == stat_key
        and str(current.get("league", "")).upper() == sport
    ]
    if not candidates:
        return None
    if prop.game:
        game_key = canonical_matchup_key(prop.game, EntryRepository.TEAM_ALIASES)
        game_matches = [
            current for current in candidates
            if canonical_matchup_key(current.get("game"), EntryRepository.TEAM_ALIASES) == game_key
        ]
        if game_matches:
            candidates = game_matches
    if team:
        team_matches = [current for current in candidates if _match_key(str(current.get("team", ""))) == team]
        if team_matches:
            candidates = team_matches
    return min(candidates, key=lambda current: abs(float(current.get("line") or 0) - float(prop.line)))


def _provider_market_issue(
    prop: PropPayload,
    platform: str,
    current_props: list[dict],
    current: dict | None,
) -> str:
    label = f"{prop.player} {prop.stat}"
    if current and current.get("context_source") == "espn_schedule":
        if _trackable_started_provider_snapshot(prop):
            return ""
        current = None
    if current is None:
        player_key = _match_key(prop.player)
        sport = prop.sport.upper()
        player_rows = [
            row for row in current_props
            if _match_key(str(row.get("player", ""))) == player_key
            and str(row.get("league", "")).upper() == sport
        ]
        if player_rows:
            return (
                f"{platform} currently lists {prop.player}, but does not offer a {prop.stat} market. "
                "Choose a stat shown on that platform or switch the entire entry to a platform that offers this market."
            )
        return (
            f"{label} is not available in the current {platform} feed. "
            "Refresh provider data or choose another platform before placing a real entry."
        )
    current_line = current.get("line")
    if current_line is not None and abs(float(current_line) - float(prop.line)) >= 0.05:
        return (
            f"{platform} does not currently offer {label} at {float(prop.line):g}; "
            f"the closest active line is {float(current_line):g}. Update the leg before placing."
        )
    return ""


def _trackable_started_provider_snapshot(prop: PropPayload) -> bool:
    start = _parse_game_time(prop.game_time)
    now = utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    if start is None or now < start:
        return False
    hours_since_start = (now - start).total_seconds() / 3600
    if hours_since_start > _sport_final_pending_hours(prop.sport) + 4:
        return False
    provider_evidence = bool(
        str(prop.provider_player_id or "").strip()
        or str(prop.player_provider or "").strip()
        or str(prop.projection_source or "").strip().lower()
        in {"provider", "provider_projection", "confirmed_provider", "prizepicks", "underdog"}
    )
    return provider_evidence and _end_to_end_prop_eligibility(prop)["eligible"]


def _hydrate_payload_prop_context(
    prop: PropPayload,
    platform: str,
    current_props: list[dict] | None = None,
) -> dict | None:
    current = _match_current_provider_prop(
        prop,
        current_props if current_props is not None else _fetch_platform_props(platform),
    )
    context = dict(current or {})
    context_game = canonical_matchup_key(context.get("game"), EntryRepository.TEAM_ALIASES)
    needs_schedule = not context.get("game_time") or "@" not in context_game
    if not context or needs_schedule:
        official = _official_game_context_for_payload_prop(prop)
        if official:
            if context:
                for key in ("game", "game_time"):
                    if not context.get(key) or (key == "game" and "@" not in context_game):
                        context[key] = official.get(key, "")
                context["schedule_context"] = True
                context["context_source"] = "espn_schedule"
            else:
                context = official
    if context:
        for key in ("team", "position", "game", "game_time", "season_type"):
            needs_value = not getattr(prop, key, None)
            if key == "game" and context.get("context_source") == "espn_schedule":
                needs_value = "@" not in canonical_matchup_key(prop.game, EntryRepository.TEAM_ALIASES)
            if needs_value and context.get(key):
                setattr(prop, key, context[key])
    return context or None


def _official_game_context_for_payload_prop(prop: PropPayload) -> dict:
    sport = str(prop.sport or "").upper()
    if sport not in {"NFL", "WNBA", "NBA", "MLB"}:
        return {}
    parsed_time = _parse_game_time(prop.game_time)
    reference = parsed_time or utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    local_date = reference.astimezone(ENTRY_DAY_TIME_ZONE).date()
    requested_game = canonical_matchup_key(prop.game, EntryRepository.TEAM_ALIASES)
    team_key = re.sub(r"[^A-Z0-9]", "", str(prop.team or "").upper())
    opponent_key = re.sub(r"[^A-Z0-9]", "", str(prop.game or "").upper())
    candidates: list[dict] = []
    for offset in (-1, 0, 1):
        try:
            candidates.extend(fetch_game_times(sport, local_date + timedelta(days=offset)))
        except Exception:
            continue
    unique_candidates: dict[tuple[str, str], dict] = {}
    for row in candidates:
        key = (
            canonical_matchup_key(row.get("game"), EntryRepository.TEAM_ALIASES),
            str(row.get("game_time") or ""),
        )
        if key[0] and key[1]:
            unique_candidates.setdefault(key, row)
    candidates = list(unique_candidates.values())
    exact = [
        row for row in candidates
        if requested_game
        and canonical_matchup_key(row.get("game"), EntryRepository.TEAM_ALIASES) == requested_game
    ]
    if exact:
        selected = exact[0]
    else:
        team_matches = []
        for row in candidates:
            row_key = canonical_matchup_key(row.get("game"), EntryRepository.TEAM_ALIASES)
            compact = row_key.replace("@", "")
            if team_key and team_key not in compact:
                continue
            if opponent_key and opponent_key != team_key and opponent_key not in compact:
                continue
            team_matches.append(row)
        if len(team_matches) != 1:
            return {}
        selected = team_matches[0]
    return {
        **selected,
        "team": prop.team,
        "context_source": "espn_schedule",
    }


def _match_key(value: str) -> str:
    return canonical_person_key(value)


def _stat_match_key(value: str) -> str:
    key = _match_key(value)
    aliases = {
        "pra": "pointsreboundsassists",
        "ptsrebsasts": "pointsreboundsassists",
        "pointsreboundsassists": "pointsreboundsassists",
        "pa": "pointsassists",
        "ptsasts": "pointsassists",
        "pointsassists": "pointsassists",
        "pr": "pointsrebounds",
        "ptsrebs": "pointsrebounds",
        "pointsrebounds": "pointsrebounds",
        "ra": "reboundsassists",
        "rebsasts": "reboundsassists",
        "reboundsassists": "reboundsassists",
        "hrbi": "hitsrunsrbis",
        "hitsrunsrbis": "hitsrunsrbis",
    }
    return aliases.get(key, key)


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


def _prop_from_payload(payload: PropPayload, entry_platform: str, *, hydrate_provider: bool = True) -> Prop:
    provider_context = _provider_context_for_payload_prop(payload, entry_platform) if hydrate_provider else {}
    projection, auto_projected, projection_source, espn_context, source_context = _analysis_projection(
        payload,
        live_sources=hydrate_provider,
    )
    direction = _prop_direction(payload.line, projection, payload.direction)
    edge = calculate_directional_edge(payload.line, projection, direction)
    confidence, confidence_adjustment = _analysis_confidence(edge, source_context, payload.stat, payload.sport, auto_projected)
    calibration = calibrate_probability(
        confidence / 100.0,
        sport=payload.sport,
        stat=payload.stat,
        provider=entry_platform or payload.platform,
        direction=direction,
        projection_source=projection_source,
        rows=_versioned_calibration_rows(),
    )
    confidence = float(calibration["probability"])
    forecast_snapshot = source_context.get("forecast") or payload.forecast_snapshot or {}
    return Prop(
        player=Player(
            name=payload.player,
            team=payload.team or str(provider_context.get("team", "") or ""),
            sport=payload.sport or str(provider_context.get("league", "") or ""),
        ),
        stat=_stat_from_text(payload.stat),
        line=payload.line,
        projection=projection,
        edge=edge,
        confidence=confidence,
        direction=direction,
        platform=_entry_platform_from_text(entry_platform or payload.platform),
        game=payload.game or str(provider_context.get("game", "") or ""),
        game_time=payload.game_time or str(provider_context.get("game_time", "") or ""),
        position=payload.position or str(provider_context.get("position", "") or ""),
        season_type=payload.season_type or str(provider_context.get("season_type", "") or ""),
        needs_projection=False,
        auto_projected=auto_projected,
        trending_count=payload.trending_count or int(provider_context.get("trending_count") or 0),
        projection_source=projection_source,
        baseline_line=payload.baseline_line or payload.standard_line or provider_context.get("baseline_line") or provider_context.get("standard_line"),
        standard_line=payload.standard_line or provider_context.get("standard_line"),
        line_offer_type=payload.line_offer_type or str(provider_context.get("line_offer_type") or "standard"),
        adjusted_line=payload.adjusted_line or bool(provider_context.get("adjusted_line")),
        is_discounted_line=payload.is_discounted_line or bool(provider_context.get("is_discounted_line")),
        is_premium_line=payload.is_premium_line or bool(provider_context.get("is_premium_line")),
        line_discount=payload.line_discount or float(provider_context.get("line_discount") or 0.0),
        espn_recent_average=espn_context.get("recent_average"),
        espn_hit_rate=espn_context.get("hit_rate"),
        espn_sample_size=int(espn_context.get("sample_size") or 0),
        espn_note=espn_context.get("note", ""),
        confidence_adjustment=confidence_adjustment,
        source_signals=source_context.get("signals", []),
        source_score=source_context.get("source_score", 0.0),
        player_identity_id=payload.player_identity_id,
        player_provider=payload.player_provider or str(provider_context.get("platform") or payload.platform or entry_platform),
        provider_player_id=payload.provider_player_id or str(provider_context.get("player_id") or ""),
        model_version=str(forecast_snapshot.get("model_version") or payload.model_version or EDGEIQ_LOCAL_MODEL_VERSION),
        feature_as_of=str(forecast_snapshot.get("feature_as_of") or payload.feature_as_of or ""),
        forecast_snapshot={
            **forecast_snapshot,
            "calibration": calibration,
            "evidence_signals": source_context.get("signals", []),
            "signal_policy": "recorded_not_hand_added",
        },
        forecast_paid_eligible=bool(forecast_snapshot.get("paid_eligible")) and bool(calibration.get("paid_eligible")),
    )


def _provider_context_for_payload_prop(payload: PropPayload, entry_platform: str) -> dict:
    if payload.game and payload.game_time and payload.team:
        return {}
    platform = _canonical_platform(entry_platform or payload.platform)
    if platform not in {"PrizePicks", "Underdog"}:
        return {}
    try:
        return _hydrate_payload_prop_context(payload, platform) or {}
    except Exception:
        return {}


def _analysis_projection(payload: PropPayload, *, live_sources: bool = True) -> tuple[float, bool, str, dict, dict]:
    if payload.projection is not None:
        direction = _prop_direction(payload.line, payload.projection, payload.direction)
        hit_rate = estimate_hit_rate(
            payload.player,
            payload.stat,
            payload.line,
            payload.projection,
            payload.trending_count,
            payload.sport,
            direction=direction,
        )
        espn_context = _espn_context(hit_rate)
        source_context = _source_context(
            payload, payload.projection, espn_context,
            apply_projection_delta=False, live_sources=live_sources,
        )
        auto_projected = bool(payload.auto_projected)
        projection_source = payload.projection_source or ("line_model" if auto_projected else "user")
        return payload.projection, auto_projected, projection_source, espn_context, source_context

    baseline_line = float(payload.baseline_line or payload.standard_line or payload.line)
    initial_direction = _normalize_direction(payload.direction or "Over")
    forecast = forecast_prop(
        payload.player,
        payload.sport,
        payload.stat,
        baseline_line,
        initial_direction,
        game_time=payload.game_time,
        team=payload.team,
        game=payload.game,
    )
    model_projection = forecast.projection
    resolved_direction = _prop_direction(payload.line, model_projection, payload.direction)
    model_probability = forecast.probability
    if resolved_direction != initial_direction:
        model_probability = 100.0 - model_probability
    hit_rate = estimate_hit_rate(
        payload.player,
        payload.stat,
        payload.line,
        model_projection,
        payload.trending_count,
        payload.sport,
        direction=resolved_direction,
    )
    context = _espn_context(hit_rate)
    source_context = _source_context(
        payload, model_projection, context,
        apply_projection_delta=False, live_sources=live_sources,
    )
    source_context["forecast"] = forecast.snapshot()
    source_context["model_probability"] = round(model_probability, 2)
    return model_projection, True, forecast.source, context, source_context


def _espn_context(hit_rate) -> dict:
    if hit_rate.source != "final_stats":
        return {
            "source": hit_rate.source,
            "sample_size": hit_rate.sample_size,
            "hit_rate": hit_rate.estimated_hit_rate,
            "note": hit_rate.note,
        }

    return {
        "source": "espn_final_stats",
        "sample_size": hit_rate.sample_size,
        "hit_rate": hit_rate.estimated_hit_rate,
        "last_5": hit_rate.last_5,
        "last_10": hit_rate.last_10,
        "season": hit_rate.season,
        "recent_average": None,
        "note": hit_rate.note,
    }


def _played_history(player: str, stat: str, sport: str | None = None, limit: int = 10, team: str = "") -> list[dict]:
    return [
        row
        for row in FinalStatsRepository.history(player, stat, sport=sport, limit=limit, team=team)
        if row.get("status", "played") != "dnp"
    ]


def _analysis_confidence(edge: float, source_context: dict, stat: str, sport: str, auto_projected: bool) -> tuple[float, float]:
    model_probability = source_context.get("model_probability")
    base = float(model_probability) if model_probability is not None else calculate_confidence(edge, stat, sport)
    return round(max(2.0, min(98.0, base)), 2), 0.0


def _source_context(
    payload: PropPayload,
    base_projection: float,
    espn_context: dict,
    apply_projection_delta: bool,
    live_sources: bool = True,
) -> dict:
    signals: list[dict] = []
    signals.extend(_espn_form_signals(payload, base_projection, espn_context))
    signals.extend(_summer_league_signals(payload, espn_context))
    signals.extend(_matchup_signals(payload))
    signals.extend(_line_movement_signals(payload))
    signals.extend(_platform_consensus_signals(payload, live_refresh=live_sources))
    if live_sources:
        signals.extend(_injury_signals(payload))
        signals.extend(_sleeper_trending_signals(payload))
        signals.extend(_balldontlie_stat_signals(payload))
        signals.extend(_news_context_signals(payload))
        signals.extend(_weather_signals(payload))
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


def _platform_consensus_signals(payload: PropPayload, *, live_refresh: bool = True) -> list[dict]:
    try:
        matches = [
            prop
            for prop in (
                _fetch_props("Both", payload.sport.upper())
                if live_refresh else _cached_props("Both", payload.sport.upper())
            )
            if canonical_person_key(prop.get("player")) == canonical_person_key(payload.player)
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
    for entry in EntryRepository.all():
        if entry.get("status") != "Settled":
            continue
        for prop in entry.get("props") or []:
            if prop.get("final_source") == "projection_estimate" or prop.get("final_result") not in {"Win", "Loss"}:
                continue
            sport_match = str(prop.get("sport", "")).upper() == payload.sport.strip().upper()
            stat_match = str(prop.get("stat", "")).lower() == payload.stat.strip().lower()
            platform_match = str(prop.get("platform") or entry.get("platform", "")).lower() == (payload.platform or "").strip().lower()
            direction_match = str(prop.get("direction") or "Over").lower() == str(payload.direction or "Over").lower()
            if sport_match and stat_match and platform_match and direction_match:
                rows.append({
                    "result": prop["final_result"],
                    "predicted": float(prop.get("confidence") or entry.get("average_confidence") or 50.0),
                    "sport": prop.get("sport", ""),
                    "stat": prop.get("stat", ""),
                    "platform": prop.get("platform") or entry.get("platform", ""),
                    "direction": prop.get("direction") or "Over",
                    "projection_source": prop.get("projection_source") or "",
                    "player": prop.get("player", ""),
                    "player_identity_id": prop.get("player_identity_id"),
                    "line": prop.get("line"),
                    "game": prop.get("game", ""),
                    "game_time": prop.get("game_time", ""),
                    "final_source": prop.get("final_source", ""),
                    "placed_at": entry.get("placed_at"),
                })
    return deduplicate_outcomes(rows)


def _versioned_calibration_rows() -> list[dict]:
    global _PREDICTION_EVIDENCE_CACHE
    now = time.monotonic()
    cached_at, cached_rows = _PREDICTION_EVIDENCE_CACHE
    if cached_at and now - cached_at < 60:
        return cached_rows
    with _PREDICTION_EVIDENCE_LOCK:
        cached_at, cached_rows = _PREDICTION_EVIDENCE_CACHE
        if cached_at and now - cached_at < 60:
            return cached_rows
        rows = [
            row
            for row in PredictionLedgerRepository.evidence_rows()
            if row.get("result") in {"Win", "Loss"}
        ]
        _PREDICTION_EVIDENCE_CACHE = (now, rows)
        return rows


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
    model_payout = _entry_payout_analysis(entry, payload)
    risk = calculate_entry_risk(entry.props)
    warnings = detect_correlations(entry)
    espn_notes = _entry_espn_notes(entry.props)
    platform_value = (
        _platform_value_check(payload)
        if payload and payload.entry_mode == "real"
        else None
    )
    risk_guardrails = _risk_guardrails(entry, payload, platform_value)
    confirmation = _confirmation_checklist(entry, payload, warnings + espn_notes)
    loss_protection = _loss_protection_payload()
    payout = (platform_value or {}).get("authoritative_economics") or model_payout
    model_result = entry_recommendation(entry, payout)
    release_verdict = _entry_release_verdict(payload, model_result, risk_guardrails, platform_value)
    corrections = _entry_correction_plan(entry, payload)
    result = {
        **model_result,
        "action": release_verdict["verdict"],
        "reason": release_verdict["summary"],
        "verdict": release_verdict["verdict"],
        "model_grade": model_result.get("grade"),
        "model_action": model_result.get("action"),
    }
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
        "platform_value": platform_value,
        "loss_protection": loss_protection,
        "payout_analysis": payout,
        "model_payout_analysis": model_payout,
        "release_verdict": release_verdict,
        "corrections": corrections,
    }


def _entry_correction_plan(entry: Entry, payload: EntryPayload | None = None) -> dict:
    legs = [_prop_correction(prop, index) for index, prop in enumerate(entry.props)]
    counts = {
        action: sum(1 for leg in legs if leg["action"] == action)
        for action in ("keep", "flip", "remove")
    }
    change_count = counts["flip"] + counts["remove"]
    if not legs:
        summary = "No props are available to review."
    elif change_count:
        summary = (
            f"EdgeIQ suggests {counts['flip']} direction change"
            f"{'s' if counts['flip'] != 1 else ''} and {counts['remove']} removal"
            f"{'s' if counts['remove'] != 1 else ''} before saving this entry."
        )
    else:
        summary = "Every leg is aligned with the current model direction and minimum evidence checks."
    return {
        "manual_entry": not bool(payload and payload.recommended_by_app),
        "summary": summary,
        "change_count": change_count,
        "counts": counts,
        "legs": legs,
    }


def _prop_correction(prop: Prop, index: int) -> dict:
    current_direction = _normalize_direction(prop.direction)
    raw_edge = float(prop.projection) - float(prop.line)
    model_direction = "Under" if raw_edge < 0 else "Over"
    edge_size = abs(raw_edge)
    quality = _prop_data_quality(prop)
    serialized = _serialize_prop(prop)
    eligibility = _end_to_end_prop_eligibility(serialized)
    alternative_confidence = calculate_confidence(edge_size, prop.stat.value, prop.player.sport)
    calibrated = calibrate_probability(
        alternative_confidence / 100.0,
        sport=prop.player.sport,
        stat=prop.stat.value,
        provider=prop.platform.value,
        direction=model_direction,
        projection_source=prop.projection_source,
        rows=_versioned_calibration_rows(),
    )
    suggested_confidence = round(float(calibrated["probability"]), 1)

    if not eligibility["eligible"]:
        action = "remove"
        reason = f"Automatic final-stat verification is unavailable: {eligibility['reasons'][0]}."
    elif quality["score"] < 42:
        action = "remove"
        reason = f"The data strength is only {quality['score']:.0f}/100 ({quality['label']})."
    elif edge_size < 0.5:
        action = "remove"
        reason = f"The projection is only {edge_size:.2f} away from the line, leaving too little model edge."
    elif model_direction != current_direction:
        action = "flip"
        reason = (
            f"The {prop.projection:.1f} projection is on the {model_direction.lower()} side of "
            f"the {prop.line:g} line."
        )
    elif float(prop.confidence) < 52:
        action = "remove"
        reason = f"Calibrated confidence is {prop.confidence:.1f}%, below the 52% review floor."
    else:
        action = "keep"
        reason = (
            f"The {prop.projection:.1f} projection supports {current_direction.lower()} "
            f"with {prop.confidence:.1f}% calibrated confidence."
        )

    if action == "flip":
        message = f"EdgeIQ suggests {model_direction} on this prop."
    elif action == "remove":
        message = "EdgeIQ suggests removing this prop."
    else:
        message = f"Keep {current_direction} on this prop."
    return {
        "index": index,
        "player": prop.player.name,
        "stat": prop.stat.value,
        "line": prop.line,
        "projection": prop.projection,
        "current_direction": current_direction,
        "suggested_direction": model_direction if action == "flip" else current_direction,
        "action": action,
        "message": message,
        "reason": reason,
        "confidence": suggested_confidence if action == "flip" else round(float(prop.confidence), 1),
        "data_quality": quality,
        "final_stats_verifiable": eligibility["eligible"],
    }


def _entry_release_verdict(
    payload: EntryPayload | None,
    model_result: dict,
    guardrails: list[dict],
    platform_value: dict | None,
) -> dict:
    mode = payload.entry_mode if payload else "paper"
    economics = (platform_value or {}).get("authoritative_economics") or {}
    complete = bool((platform_value or {}).get("complete_on_recommended_platform"))
    expected_value = float(economics.get("expected_value") or 0.0)
    profit_probability = float(economics.get("profit_probability") or 0.0)
    break_even = float(economics.get("break_even_probability") or 0.0)
    hard_blocks = [guard["message"] for guard in guardrails if guard.get("severity") == "danger"]
    warnings = [guard["message"] for guard in guardrails if guard.get("severity") == "warning"]

    if mode == "paper":
        verdict = "Paper"
        reasons = ["Paper entries build calibration without risking bankroll."]
    elif not complete:
        verdict = "Watch"
        reasons = ["A complete current provider match is required before paid placement."]
    elif expected_value <= 0:
        verdict = "Avoid"
        reasons = [f"Best provider-specific expected value is {expected_value:.1f}%, which is not positive."]
    elif hard_blocks:
        verdict = "Paper"
        reasons = hard_blocks
    elif profit_probability < break_even:
        verdict = "Watch"
        reasons = [
            f"Estimated profit probability {profit_probability:.1f}% is below the "
            f"{break_even:.1f}% provider break-even threshold."
        ]
    else:
        verdict = "Paid"
        reasons = ["Positive provider EV and all paid-entry release checks passed."]

    paid_allowed = verdict == "Paid" and not hard_blocks and complete and expected_value > 0
    summary = reasons[0]
    return {
        "verdict": verdict,
        "paid_allowed": paid_allowed,
        "authoritative_platform": (platform_value or {}).get("authoritative_platform"),
        "expected_value": round(expected_value, 2),
        "profit_probability": round(profit_probability, 2),
        "break_even_probability": round(break_even, 2),
        "reasons": reasons,
        "warnings": warnings,
        "model_grade": model_result.get("grade"),
        "model_score": model_result.get("score"),
        "summary": summary,
    }


def _entry_payout_analysis(entry: Entry, payload: EntryPayload | None = None) -> dict:
    return payout_analysis(
        [float(prop.confidence or 0.0) / 100.0 for prop in entry.props],
        payload.platform if payload else entry.platform.value,
        payload.payout_type if payload else "standard",
        displayed_multiplier=payload.multiplier if payload else None,
        correlation_matrix=estimate_correlation_matrix(entry.props),
        exact_schedule=payload.payout_schedule or None if payload else None,
    )


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
        score -= 8
        flags.append("projection was auto-filled")
    else:
        score += 8
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


def _cached_dashboard_stats() -> dict:
    global _SEGMENT_DASHBOARD_CACHE
    now = time.monotonic()
    dependency_token = get_dashboard
    with _SEGMENT_DASHBOARD_LOCK:
        if _SEGMENT_DASHBOARD_CACHE[0] > now and _SEGMENT_DASHBOARD_CACHE[1] == dependency_token:
            return _SEGMENT_DASHBOARD_CACHE[2]
        dashboard_stats = get_dashboard()
        _SEGMENT_DASHBOARD_CACHE = (now + 15.0, dependency_token, dashboard_stats)
        return dashboard_stats


def _entry_segment_flags(props: list[dict | Prop], platform: str = "") -> list[dict]:
    dashboard_stats = _cached_dashboard_stats()
    flags: list[dict] = []

    def prop_value(prop: dict | Prop, name: str, default: str = "") -> str:
        if isinstance(prop, dict):
            return str(prop.get(name) or default)
        if name == "sport":
            return str(prop.player.sport or default)
        if name == "stat":
            return str(prop.stat.value or default)
        if name == "platform":
            return str(prop.platform.value or default)
        return default

    def add_group_flag(group_type: str, name: str, stats: dict) -> None:
        decisions = int(stats.get("wins", 0) or 0) + int(stats.get("losses", 0) or 0)
        if decisions < 3:
            return
        roi = float(stats.get("roi", 0.0) or 0.0)
        win_rate = float(stats.get("win_pct", stats.get("win_rate", 0.0)) or 0.0)
        if roi <= -25 or win_rate < 35:
            flags.append({
                "severity": "danger",
                "message": f"{group_type} segment {name} is weak ({win_rate:.1f}% win rate, {roi:.1f}% ROI); route to paper/watch.",
            })
        elif roi < 0 or win_rate < 45:
            flags.append({
                "severity": "warning",
                "message": f"{group_type} segment {name} is underperforming ({win_rate:.1f}% win rate, {roi:.1f}% ROI).",
            })

    sports = sorted({prop_value(prop, "sport").upper() for prop in props if prop_value(prop, "sport")})
    stats = sorted({prop_value(prop, "stat") for prop in props if prop_value(prop, "stat")})
    platforms = sorted({prop_value(prop, "platform") for prop in props if prop_value(prop, "platform")})
    if platform:
        platforms.append(platform)

    for sport in sports:
        row = (dashboard_stats.get("by_sport") or {}).get(sport)
        if row:
            add_group_flag("Sport", sport, row)
    for platform_name in sorted({_canonical_platform(name) for name in platforms if name}):
        row = (dashboard_stats.get("by_platform") or {}).get(platform_name)
        if row:
            add_group_flag("Platform", platform_name, row)
    for stat in stats:
        row = (dashboard_stats.get("by_stat") or {}).get(stat)
        if row:
            add_group_flag("Stat", stat, row)
    return flags[:4]


def _risk_guardrails(
    entry: Entry,
    payload: EntryPayload | None,
    platform_value: dict | None = None,
) -> list[dict]:
    prefs = _user_preferences()
    strategy = _bankroll_strategy()
    dashboard_stats = _cached_dashboard_stats()
    bankroll = float(dashboard_stats.get("bankroll") or get_starting_bankroll() or 0)
    wager = float(payload.wager if payload else 0.0)
    guards: list[dict] = []
    if wager and bankroll and wager > bankroll * (prefs["max_wager_pct"] / 100):
        severity = "danger" if wager > bankroll * (max(prefs["max_wager_pct"] * 3, 25) / 100) else "warning"
        guards.append({
            "severity": severity,
            "message": f"Wager exceeds {prefs['max_wager_pct']:.1f}% of bankroll.",
        })
    if payload and payload.entry_mode == "real" and wager and bankroll:
        single_cap = bankroll * float(strategy["max_wager_pct"]) / 100
        if wager > single_cap:
            severity = "danger" if wager > bankroll * (max(float(strategy["max_wager_pct"]) * 3, 25.0) / 100) else "warning"
            guards.append({
                "severity": severity,
                "message": f"Wager exceeds strategy cap of {strategy['max_wager_pct']:.1f}% bankroll.",
            })
        open_exposure = _open_real_money_exposure()
        exposure_cap = bankroll * float(strategy["max_open_exposure_pct"]) / 100
        if open_exposure + wager > exposure_cap:
            guards.append({
                "severity": "danger",
                "message": f"Open exposure would exceed {strategy['max_open_exposure_pct']:.1f}% bankroll.",
            })
        monthly_profit = _money_value(dashboard_stats.get("monthly_profit"))
        stop_loss_amount = bankroll * float(strategy["stop_loss_pct"]) / 100
        if monthly_profit < 0 and abs(monthly_profit) >= stop_loss_amount:
            guards.append({
                "severity": "danger",
                "message": f"Monthly stop-loss reached ({strategy['stop_loss_pct']:.1f}% bankroll). Route new entries to paper.",
            })
        elif monthly_profit < 0 and abs(monthly_profit) >= stop_loss_amount * 0.75:
            guards.append({
                "severity": "warning",
                "message": "Monthly drawdown is near the stop-loss threshold.",
            })
    if entry.prop_count >= 4 and not prefs["allow_high_risk"]:
        guards.append({"severity": "danger", "message": "Preferences block high-risk entries with four or more legs."})
    if prefs["avoid_same_game"] and len({prop.game for prop in entry.props if prop.game}) < len([prop for prop in entry.props if prop.game]):
        guards.append({"severity": "warning", "message": "Multiple legs share a game; correlation risk is elevated."})
    if entry.average_confidence < 50:
        guards.append({"severity": "warning", "message": "Average confidence is below 50%."})
    if entry.average_edge < 0:
        guards.append({"severity": "warning", "message": "Average projected edge is negative."})
    if payload and payload.entry_mode == "real":
        shadow = ModelRehabilitationRepository.shadow_status()
        if payload.recommended_by_app and not shadow.get("release_ready"):
            guards.append({
                "severity": "danger",
                "message": (
                    "The current model version is still in shadow evaluation. "
                    f"{shadow.get('settled', 0)}/100 verified shadow decisions have settled."
                ),
            })
        unproven = [prop.player.name for prop in entry.props if not prop.forecast_paid_eligible]
        if unproven:
            guards.append({
                "severity": "danger" if payload.recommended_by_app else "warning",
                "message": (
                    "EdgeIQ-generated paid cards require versioned forecast and calibration evidence for every leg. "
                    f"{', '.join(unproven[:3])} should remain paper/watch; a manually chosen entry can still be logged."
                ),
            })
        if payload.payout_type == "flex" and not payload.payout_schedule:
            guards.append({
                "severity": "danger",
                "message": "Enter the exact flex payout table shown by the provider before paid placement.",
            })
        payout = (platform_value or {}).get("authoritative_economics") or {}
        if not payout.get("payouts"):
            guards.append({"severity": "danger", "message": "No complete provider-backed payout could be verified for this entry."})
        elif float(payout.get("expected_value") or 0.0) <= 0:
            guards.append({
                "severity": "danger",
                "message": f"Provider-specific expected value is {float(payout.get('expected_value') or 0.0):.1f}%; paid entries require positive EV.",
            })
        guards.extend(_market_consensus_guardrails(entry, platform_value or {}, payload))
        guards.extend(_pending_portfolio_exposure_flags(entry))
    segment_flags = _entry_segment_flags(entry.props, payload.platform if payload else entry.platform.value)
    if payload and payload.entry_mode == "real":
        guards.extend(segment_flags)
        guards.extend(_loss_protection_entry_flags(entry, payload))
        value_legs = (platform_value or {}).get("legs") or []
        missing = [row for row in value_legs if not row.get("platforms")]
        if missing and payload.recommended_by_app:
            guards.append({
                "severity": "danger",
                "message": "App-recommended real entries must match the current provider board before placement.",
            })
        elif missing:
            guards.append({
                "severity": "warning",
                "message": "One or more legs could not be matched to the current provider board.",
            })
    elif segment_flags:
        guards.extend({**flag, "severity": "warning"} for flag in segment_flags)
    if not guards:
        guards.append({"severity": "info", "message": "No hard bankroll or correlation guardrails triggered."})
    return guards


def _open_real_money_exposure() -> float:
    return round(sum(
        float(entry.get("wager") or 0.0)
        for entry in EntryRepository.pending()
        if entry.get("entry_mode", "real") == "real"
    ), 2)


def _market_consensus_guardrails(
    entry: Entry,
    platform_value: dict,
    payload: EntryPayload,
) -> list[dict]:
    legs = platform_value.get("legs") or []
    by_market = {
        (
            canonical_person_key(leg.get("player")),
            _settlement_stat_key(leg.get("stat")),
        ): leg.get("market_consensus") or {}
        for leg in legs
    }
    flags = []
    for prop in entry.props:
        market = by_market.get(
            (canonical_person_key(prop.player.name), _settlement_stat_key(prop.stat.value)),
            {},
        )
        if not market.get("available"):
            flags.append({
                "severity": "danger" if payload.recommended_by_app else "warning",
                "message": (
                    f"{prop.player.name} {prop.stat.value} has no exact-line multi-book probability; "
                    "keep app-generated paid use blocked."
                ),
            })
            continue
        book_count = int(market.get("book_count") or 0)
        if book_count < 2:
            flags.append({
                "severity": "danger" if payload.recommended_by_app else "warning",
                "message": f"{prop.player.name} has only {book_count} paired sportsbook price; require at least 2.",
            })
        if market.get("stale"):
            flags.append({
                "severity": "danger",
                "message": f"{prop.player.name} market odds are stale; refresh before paid placement.",
            })
        market_probability = market.get("market_probability")
        if market_probability is None:
            continue
        disagreement = abs(float(prop.confidence or 0.0) - float(market_probability))
        if disagreement >= 20:
            flags.append({
                "severity": "danger" if disagreement >= 30 else "warning",
                "message": (
                    f"{prop.player.name} model and no-vig market differ by {disagreement:.1f} points; "
                    "inspect the evidence before using this leg."
                ),
            })
    return flags[:5]


def _pending_portfolio_exposure_flags(entry: Entry) -> list[dict]:
    pending = EntryRepository.pending()
    exact_matches: set[tuple[str, str, str]] = set()
    player_matches: set[str] = set()
    game_matches: set[str] = set()
    for prop in entry.props:
        player_key = canonical_person_key(prop.player.name)
        stat_key = _settlement_stat_key(prop.stat.value)
        direction = _normalize_direction(prop.direction)
        game_key = canonical_matchup_key(prop.game)
        for pending_entry in pending:
            for pending_prop in pending_entry.get("props") or []:
                if canonical_person_key(pending_prop.get("player")) == player_key:
                    player_matches.add(prop.player.name)
                    if (
                        _settlement_stat_key(pending_prop.get("stat")) == stat_key
                        and _normalize_direction(pending_prop.get("direction") or "Over") == direction
                    ):
                        exact_matches.add((prop.player.name, prop.stat.value, direction))
                if game_key and canonical_matchup_key(pending_prop.get("game")) == game_key:
                    game_matches.add(prop.game)
    flags = []
    if exact_matches:
        labels = ", ".join(f"{player} {direction} {stat}" for player, stat, direction in sorted(exact_matches))
        flags.append({
            "severity": "danger",
            "message": f"Duplicate pending market exposure: {labels}. Wait for the existing position to settle or use paper mode.",
        })
    elif player_matches:
        flags.append({
            "severity": "warning",
            "message": f"Pending entries already include {', '.join(sorted(player_matches))}; total player exposure is concentrated.",
        })
    if game_matches:
        flags.append({
            "severity": "warning",
            "message": f"Pending entries already include {len(game_matches)} matching game{'s' if len(game_matches) != 1 else ''}; review correlated portfolio risk.",
        })
    return flags


def _money_value(value: object) -> float:
    if isinstance(value, dict):
        for key in ("profit", "amount", "value", "current"):
            if key in value:
                return _money_value(value.get(key))
        return 0.0
    try:
        return float(str(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _confirmation_checklist(entry: Entry, payload: EntryPayload | None, warnings: list[str]) -> list[dict]:
    props = entry.props
    has_summer_league = any(prop.season_type == "summer_league" for prop in props)
    with ThreadPoolExecutor(max_workers=min(3, max(1, len(props)))) as pool:
        availability_rows = list(pool.map(
            lambda prop: _player_availability_payload(
                prop.player.name,
                prop.player.sport,
                prop.player.team,
                prop.game,
            ),
            props,
        ))
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


def _entry_audit_snapshot(
    entry: Entry,
    payload: EntryPayload,
    analysis: dict,
    settlement_warnings: list[str] | None = None,
) -> dict:
    settlement_warnings = settlement_warnings or []
    return {
        "schema_version": AUDIT_SNAPSHOT_SCHEMA_VERSION,
        "model_version": EDGEIQ_LOCAL_MODEL_VERSION,
        "created_at": iso_utc(utc_now()),
        "platform": payload.platform,
        "wager": payload.wager,
        "multiplier": payload.multiplier,
        "payout_type": payload.payout_type,
        "payout_analysis": analysis.get("payout_analysis", {}),
        "entry_mode": payload.entry_mode,
        "recommended_by_app": payload.recommended_by_app,
        "recommendation_snapshot_id": payload.recommendation_snapshot_id,
        "tracking_override": bool(payload.tracking_override),
        "settlement_tracking": "manual_verification_required" if settlement_warnings else "verified",
        "settlement_warnings": settlement_warnings,
        "recommendation": analysis.get("recommendation", {}),
        "risk": analysis.get("risk", {}),
        "warnings": analysis.get("warnings", []),
        "source_fusion": analysis.get("source_fusion", {}),
        "loss_protection": analysis.get("loss_protection", {}),
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
        "max_open_exposure_pct": 15.0,
        "stop_loss_pct": 12.0,
        "max_player_entries": 2,
        "max_game_entries": 3,
        "max_market_entries": 1,
        "max_player_exposure_pct": 7.5,
        "paper_first": False,
    }
    stored = _safe_json_loads(SettingsRepository.get("bankroll_strategy", ""))
    strategy: dict[str, object] = {**defaults, **stored}
    strategy["mode"] = strategy["mode"] if strategy["mode"] in {"flat", "conservative", "balanced", "aggressive", "kelly", "paper"} else "balanced"
    strategy["unit_size"] = max(0.0, float(str(strategy.get("unit_size") or defaults["unit_size"])))
    strategy["max_wager_pct"] = max(0.1, min(100.0, float(str(strategy.get("max_wager_pct") or defaults["max_wager_pct"]))))
    strategy["max_open_exposure_pct"] = max(0.1, min(100.0, float(str(strategy.get("max_open_exposure_pct") or defaults["max_open_exposure_pct"]))))
    strategy["stop_loss_pct"] = max(0.1, min(100.0, float(str(strategy.get("stop_loss_pct") or defaults["stop_loss_pct"]))))
    strategy["max_player_entries"] = max(1, min(20, int(strategy.get("max_player_entries") or defaults["max_player_entries"])))
    strategy["max_game_entries"] = max(1, min(20, int(strategy.get("max_game_entries") or defaults["max_game_entries"])))
    strategy["max_market_entries"] = max(1, min(10, int(strategy.get("max_market_entries") or defaults["max_market_entries"])))
    strategy["max_player_exposure_pct"] = max(0.1, min(100.0, float(str(strategy.get("max_player_exposure_pct") or defaults["max_player_exposure_pct"]))))
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
        canonical_person_key(item.get("player")),
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
            if not same_person(item["player"], raw.get("player")):
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
    with _PROP_FETCH_LOCK:
        platform_memory = {
            platform: dict(metrics)
            for platform, metrics in _PROP_FETCH_METRICS.items()
        }
    return build_data_health_payload(
        _provider_weights(),
        platform_memory,
        SETTLEMENT_REFRESH_STATUS_KEY,
        _endpoint_timing_snapshot(),
        operational_health={
            "scheduler": _safe_json_loads(SettingsRepository.get("daily_scheduler_status", "")),
            "schedule": _refresh_schedule_payload(),
            "shadow_settlement": _safe_json_loads(SettingsRepository.get("shadow_settlement_status", "")),
            "shadow_evaluation": ModelRehabilitationRepository.shadow_status(),
            "research_memory": ResearchEvidenceRepository.summary(),
            "complete_board": BoardOfferRepository.summary(),
            "plausibility_rejections": PlausibilityRejectionRepository.recent(limit=25),
        },
    )


def _runtime_status_payload() -> dict:
    data_health = _data_health_payload()
    model_health = _model_health_payload()
    ai = build_ai_status_payload(
        os.getenv("OPENAI_API_KEY", ""),
        ollama_status=lambda: ollama_status(),
        openai_model=lambda: _openai_model(),
        openai_vision_model=lambda: _openai_vision_model(),
        local_model_version=EDGEIQ_LOCAL_MODEL_VERSION,
    )
    operations = data_health.get("operations") or {}
    scheduler = operations.get("scheduler") or {}
    settlement = _safe_json_loads(SettingsRepository.get(SETTLEMENT_REFRESH_STATUS_KEY, ""))
    provider_summary = data_health.get("summary") or {}
    paid_enabled = model_health.get("paid_entry_mode") == "enabled"
    return {
        "overall": "ready" if not provider_summary.get("warnings") and paid_enabled else "attention",
        "items": [
            {
                "key": "ollama", "label": "Ask EdgeIQ",
                "status": "ready" if (ai.get("ollama") or {}).get("available") else "attention",
                "value": (ai.get("ollama") or {}).get("model") or "Local fallback",
                "detail": (ai.get("ollama") or {}).get("note") or ai.get("note") or "Status unavailable.",
            },
            {
                "key": "scheduler", "label": "Scheduler",
                "status": "ready" if scheduler.get("ran_at") and not scheduler.get("failures") else "attention",
                "value": "Running" if scheduler.get("ran_at") else "No run recorded",
                "detail": f"Last run {scheduler.get('ran_at') or 'not recorded'}.",
            },
            {
                "key": "settlement", "label": "Settlement",
                "status": "ready" if settlement.get("ran_at") and not settlement.get("error") else "attention",
                "value": "Active" if settlement.get("ran_at") else "Waiting",
                "detail": settlement.get("message") or f"Last check {settlement.get('ran_at') or 'not recorded'}.",
            },
            {
                "key": "providers", "label": "Provider Data",
                "status": "ready" if not provider_summary.get("warnings") else "attention",
                "value": f"{provider_summary.get('connected', 0)}/{provider_summary.get('total', 0)} available",
                "detail": f"{provider_summary.get('warnings', 0)} source or operations warning(s).",
            },
            {
                "key": "model", "label": "Model Release",
                "status": "ready" if paid_enabled else "attention",
                "value": "Paid enabled" if paid_enabled else "Paper first",
                "detail": f"Trust {float(model_health.get('trust_score') or 0):.0f}/100 · {model_health.get('status') or 'Status unavailable'}.",
            },
        ],
        "updated_at": iso_utc(utc_now()),
    }


def _verify_odds_provider() -> dict:
    attempted_at = iso_utc(utc_now())
    result = sportsbook_odds.verify_connection()
    _record_provider_fetch_status(
        "The Odds API",
        attempted_at,
        row_count=int(result.get("sports") or 0),
        error="" if result.get("ok") else str(result.get("message") or "Verification failed."),
    )
    return result


def _refresh_schedule_payload() -> dict:
    defaults = {
        "morning_scan": "08:00",
        "injury_refresh": "11:00",
        "line_snapshots": "*/30",
        "result_check": "23:30",
        "nightly_calibration": "02:00",
        "shadow_cohort": "08:15",
        "auto_paper_samples": "08:30",
        "enabled": True,
    }
    schedule = {**defaults, **_safe_json_loads(SettingsRepository.get("refresh_schedule", ""))}
    jobs = [
        {"name": "Morning board scan", "time": schedule["morning_scan"], "action": "Refresh props, command center, timing alerts."},
        {"name": "Injury/news refresh", "time": schedule["injury_refresh"], "action": "Update availability, injuries, news context."},
        {"name": "Line movement snapshots", "time": schedule["line_snapshots"], "action": "Record prop lines for CLV and timing alerts."},
        {"name": "Post-game result check", "time": schedule["result_check"], "action": "Auto-check pending entries against final stats."},
        {"name": "Nightly calibration", "time": schedule["nightly_calibration"], "action": "Rebuild model health and confidence calibration."},
        {"name": "Daily shadow cohort", "time": schedule["shadow_cohort"], "action": "Store prospective model-versioned recommendations for verified evaluation."},
        {"name": "Automatic paper samples", "time": schedule["auto_paper_samples"], "action": "Create zero-wager cards for weak calibration segments."},
    ]
    now = datetime.now(ENTRY_DAY_TIME_ZONE)
    job_keys = ("morning_scan", "injury_refresh", "line_snapshots", "result_check", "nightly_calibration", "shadow_cohort", "auto_paper_samples")
    for job, key in zip(jobs, job_keys, strict=True):
        last_run = SettingsRepository.get(f"daily_scheduler_run:{key}", "")
        job["key"] = key
        job["last_run"] = last_run
        job["overdue"] = _scheduled_job_overdue(str(job["time"]), last_run, now)
    return {
        "schedule": schedule,
        "jobs": jobs,
        "last_run": SettingsRepository.get("last_daily_refresh", ""),
        "scheduler": _safe_json_loads(SettingsRepository.get("daily_scheduler_status", "")),
        "overdue_jobs": [job for job in jobs if job.get("overdue")],
    }


def _run_daily_refresh_now() -> dict:
    with named_operation_lock("daily-provider-refresh") as acquired:
        if not acquired:
            return {
                "accepted": True,
                "skipped": True,
                "message": "A provider refresh is already running.",
            }
        return build_run_daily_refresh_payload(
            run_sync=lambda: run_sync(),
            now=lambda: utc_now(),
            iso_time=lambda value: iso_utc(value),
            save_setting=lambda key, value: SettingsRepository.set(key, value),
            user_preferences=lambda: _user_preferences(),
            run_scan=lambda platform, sport_filter, sync_result: _run_daily_briefing_scan(
                platform,
                sport_filter,
                trigger="daily_refresh",
                sync_result=sync_result,
            ),
            refresh_schedule=lambda: _refresh_schedule_payload(),
        )


def _run_due_daily_operations() -> dict:
    with named_operation_lock("daily-maintenance") as acquired:
        if not acquired:
            return {
                "ok": True,
                "skipped": True,
                "jobs_run": [],
                "message": "Another EdgeIQ process is already running scheduled maintenance.",
            }
        return _run_due_daily_operations_locked()


def _run_due_daily_operations_locked() -> dict:
    schedule_payload = _refresh_schedule_payload()
    schedule = schedule_payload["schedule"]
    if not schedule.get("enabled", True):
        return {"ok": True, "message": "Daily scheduler is disabled."}
    now = datetime.now(ENTRY_DAY_TIME_ZONE)
    minute_key = now.strftime("%Y-%m-%dT%H:%M")
    day_key = now.strftime("%Y-%m-%d")
    due: list[tuple[str, object]] = []
    timed_jobs = {
        "morning_scan": _run_daily_refresh_now,
        "injury_refresh": _run_daily_refresh_now,
        "result_check": lambda: {
            "entries": _auto_check_pending_entries(False, True),
            "shadow": ModelRehabilitationRepository.settle_pending(),
            "complete_board": _refresh_and_settle_complete_board(),
        },
        "nightly_calibration": lambda: _backtest_payload(),
        "shadow_cohort": _queue_daily_shadow_cohort,
        "auto_paper_samples": _run_automatic_paper_samples,
    }
    for name, callback in timed_jobs.items():
        scheduled_time = str(schedule.get(name) or "")
        run_key = f"daily_scheduler_run:{name}"
        last_run = SettingsRepository.get(run_key, "")
        if scheduled_time and now.strftime("%H:%M") >= scheduled_time and not str(last_run).startswith(day_key):
            due.append((name, callback))
    snapshot_rule = str(schedule.get("line_snapshots") or "")
    if snapshot_rule.startswith("*/"):
        try:
            interval = max(1, int(snapshot_rule[2:]))
            last_snapshot = SettingsRepository.get("daily_scheduler_run:line_snapshots", "")
            if _elapsed_job_due(last_snapshot, now, interval):
                due.append(("line_snapshots", lambda: {
                    platform: len(_fetch_platform_props(platform, force_refresh=True))
                    for platform in ENTRY_PLATFORMS
                }))
        except ValueError:
            pass
    if _odds_provider_recovery_due(now):
        due.append(("odds_provider_recovery", _verify_odds_provider))
    completed = []
    failures = []
    for name, callback in due:
        run_key = f"daily_scheduler_run:{name}"
        if name == "line_snapshots" and SettingsRepository.get(run_key, "") == minute_key:
            continue
        try:
            result = callback()
            SettingsRepository.set(run_key, minute_key)
            completed.append({"job": name, "result": result})
        except Exception as exc:
            failures.append({"job": name, "message": str(exc) or "Scheduled job failed."})
    status = {
        "ran_at": iso_utc(utc_now()),
        "jobs_run": [row["job"] for row in completed],
        "failures": failures,
        "ok": not failures,
        "message": "Scheduled maintenance completed." if not failures else "Some scheduled maintenance needs attention.",
    }
    SettingsRepository.set("daily_scheduler_status", json.dumps(status))
    return status


def _elapsed_job_due(last_run: str, now: datetime, interval_minutes: int) -> bool:
    if not last_run:
        return True
    try:
        previous = datetime.fromisoformat(str(last_run).replace("Z", "+00:00"))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=now.tzinfo)
        return (now - previous.astimezone(now.tzinfo)).total_seconds() >= interval_minutes * 60
    except (TypeError, ValueError):
        return True


def _scheduled_job_overdue(rule: str, last_run: str, now: datetime) -> bool:
    if rule.startswith("*/"):
        try:
            return _elapsed_job_due(last_run, now, max(1, int(rule[2:])) * 2)
        except ValueError:
            return False
    if not rule or now.strftime("%H:%M") < rule:
        return False
    return not str(last_run).startswith(now.strftime("%Y-%m-%d"))


def _odds_provider_recovery_due(now: datetime) -> bool:
    if not os.getenv("ODDS_API_KEY", "").strip():
        return False
    runtime = _safe_json_loads(SettingsRepository.get(_provider_status_key("The Odds API"), ""))
    age = _age_minutes(runtime.get("last_success_at"))
    if age is not None and age < 60:
        return False
    return _elapsed_job_due(SettingsRepository.get("daily_scheduler_run:odds_provider_recovery", ""), now, 60)


def _queue_daily_shadow_cohort() -> dict:
    feed = ModelRehabilitationRepository.load_feed()
    rows = feed.get("opportunity_feed", {}).get("opportunities") or feed.get("props") or []
    if not rows:
        rows = _fetch_props("All Platforms", None)
    return ModelRehabilitationRepository.queue_shadow(
        rows,
        model_version=f"{EDGEIQ_LOCAL_MODEL_VERSION}-shadow-v2.2.1",
        target=227,
    )


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
    for alert in _cached_briefing_timing_alerts()[:3]:
        notices.append({
            "type": "Market Timing",
            "severity": alert["severity"],
            "title": f"{alert['type']}: {alert['player']}",
            "message": alert["reason"],
        })
    return {"notifications": notices[:12], "count": min(len(notices), 12)}


def _cached_briefing_timing_alerts() -> list[dict]:
    """Build notification alerts without starting another live provider scan."""
    try:
        briefing = _cached_daily_briefing_payload(
            "PrizePicks",
            None,
            cached_only=True,
        )
    except Exception:
        return []

    alerts: list[dict] = []
    sections = briefing.get("sections") or {}
    for section in ("bet", "watch", "paper"):
        for card in sections.get(section) or []:
            timing = card.get("timing") or {}
            props = card.get("props") or []
            if not timing or not props:
                continue
            prop = props[0]
            alerts.append({
                "type": timing.get("label") or timing.get("type") or "Market update",
                "severity": timing.get("severity") or ("positive" if section == "bet" else "watch"),
                "player": prop.get("player") or card.get("title") or "Recommended prop",
                "reason": " ".join(timing.get("notes") or []) or card.get("reason") or "Review the current line before placing.",
                "priority_score": float(timing.get("score") or card.get("score") or 0.0),
            })
    alerts.sort(key=lambda alert: alert["priority_score"], reverse=True)
    return alerts


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


def _bounded_player_availability_payload(
    player: str,
    sport: str,
    team: str = "",
    game: str = "",
    *,
    timeout_seconds: float = 3.0,
) -> dict:
    """Keep optional live context from delaying the core statistical report."""
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_player_availability_payload, player, sport, team, game)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        return {
            "player": player,
            "sport": sport,
            "team": team,
            "game": game,
            "availability_score": None,
            "status": "Live context pending",
            "factors": ["The statistical report is ready. Injury and news checks are still refreshing."],
        }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _accuracy_lab_payload() -> dict:
    return build_accuracy_lab_payload()


def _serialize_entry(entry: Entry) -> dict:
    return {
        "platform": entry.platform.value,
        "average_confidence": round(entry.average_confidence, 2),
        "average_edge": round(entry.average_edge, 2),
        "props": [_serialize_prop(prop) for prop in entry.props],
    }


def _serialize_prop(prop: Prop) -> dict:
    quality = _prop_data_quality(prop)
    data_strength = _data_strength_labels({
        "player": prop.player.name,
        "team": prop.player.team,
        "position": prop.position,
        "sport": prop.player.sport,
        "stat": prop.stat.value,
        "game": prop.game,
        "game_time": prop.game_time,
        "auto_projected": prop.auto_projected,
        "provider_backed": not prop.auto_projected,
        "data_quality": quality,
        "espn": {"sample_size": prop.espn_sample_size},
        "hit_rate": {"sample_size": prop.espn_sample_size, "source": "final_stats" if prop.espn_sample_size else ""},
    })
    serialized = {
        "player": prop.player.name,
        "player_identity_id": prop.player_identity_id,
        "player_provider": prop.player_provider,
        "provider_player_id": prop.provider_player_id,
        "provider_projection_id": prop.provider_projection_id,
        "provider_offer_verified": prop.provider_offer_verified,
        "team": prop.player.team,
        "position": prop.position,
        "sport": prop.player.sport,
        "stat": prop.stat.value,
        "line": prop.line,
        "baseline_line": prop.baseline_line,
        "standard_line": prop.standard_line,
        "line_offer_type": prop.line_offer_type,
        "adjusted_line": prop.adjusted_line,
        "is_discounted_line": prop.is_discounted_line,
        "is_premium_line": prop.is_premium_line,
        "line_discount": prop.line_discount,
        "projection": prop.projection,
        "direction": prop.direction,
        "edge": round(prop.edge, 2),
        "confidence": round(prop.confidence, 2),
        "platform": prop.platform.value,
        "game": prop.game,
        "game_time": prop.game_time,
        "season_type": prop.season_type,
        "auto_projected": prop.auto_projected,
        "provider_backed": not prop.auto_projected,
        "trending_count": prop.trending_count,
        "projection_source": prop.projection_source,
        "model_version": prop.model_version,
        "feature_as_of": prop.feature_as_of,
        "forecast_snapshot": prop.forecast_snapshot or {},
        "forecast_paid_eligible": prop.forecast_paid_eligible,
        "projection_type": "auto-projected" if prop.auto_projected else "provider-backed",
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
        "data_strength": data_strength,
    }
    serialized["risk_profile"] = _prop_risk_profile(serialized)
    age = _age_minutes(serialized.get("feature_as_of"))
    serialized["recommendation_freshness"] = {
        "status": "expired" if age is not None and age > 30 else "fresh",
        "age_minutes": round(age, 1) if age is not None else None,
        "expires_after_minutes": 30,
    }
    return serialized


def _serialize_suggestion(suggestion, include_release: bool = True) -> dict:
    leg_count = suggestion.entry.prop_count
    entry = _serialize_entry(suggestion.entry)
    trust = _trust_score_for_props(entry["props"], suggestion.warnings)
    card = {
        "type": "entry",
        "grade": suggestion.grade,
        "action": suggestion.action,
        "score": suggestion.score,
        "props": entry["props"],
        "warnings": suggestion.warnings,
        "trust": trust,
        "suggestion": {"entry": entry},
    }
    serialized = {
        "rank": suggestion.rank,
        "score": suggestion.score,
        "grade": suggestion.grade,
        "action": suggestion.action,
        "leg_count": leg_count,
        "risk_tier": "Higher Risk" if leg_count >= 4 else "Standard",
        "warnings": suggestion.warnings,
        "entry": entry,
        "trust": trust,
    }
    if include_release:
        serialized["release_status"] = _card_release_status(card)
        if not serialized["release_status"]["ok"] and "pass" not in str(serialized["action"]).lower():
            serialized["action"] = "Track on Paper"
    _stamp_current_recommendation_lineage(serialized, groups=("props",))
    entry["recommendation_snapshot_id"] = serialized.get("recommendation_snapshot_id", "")
    for prop in entry["props"]:
        prop["recommendation_snapshot_id"] = serialized.get("recommendation_snapshot_id", "")
    return serialized


def _stamp_current_recommendation_lineage(payload: dict, *, groups: tuple[str, ...] = ()) -> dict:
    feed = ModelRehabilitationRepository.load_feed()
    snapshot_id = str(feed.get("snapshot_id") or "")
    model_version = str(feed.get("model_version") or EDGEIQ_LOCAL_MODEL_VERSION)
    if not snapshot_id:
        return payload
    payload["recommendation_snapshot_id"] = snapshot_id
    payload["model_version"] = model_version
    for key in groups:
        for row in payload.get(key) or []:
            if isinstance(row, dict):
                row["recommendation_snapshot_id"] = snapshot_id
                row["model_version"] = model_version
    return payload


def _serialize_pending(entry: dict) -> dict:
    return {
        "id": entry.get("id"),
        "platform": entry.get("platform", ""),
        "entry_mode": entry.get("entry_mode", "real"),
        "wager": entry.get("wager", 0.0),
        "multiplier": entry.get("multiplier", 1.0),
        "potential_payout": entry.get("potential_payout", 0.0),
        "placed_at": iso_utc(entry.get("placed_at")),
        "props": [
            {
                "player": prop.get("player", ""),
                "direction": prop.get("direction", "Over"),
                "stat": prop.get("stat", ""),
                "line": prop.get("line"),
            }
            for prop in entry.get("props", [])
        ],
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


def _serialize_bet_history_entry(
    entry: dict,
    settlement_evidence: dict[int, dict] | None = None,
    line_histories: dict[tuple[str, str, str, str, str], list[dict]] | None = None,
) -> dict:
    props = entry.get("props") or []
    evidence_by_prop = settlement_evidence or {}
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
        "payout_type": entry.get("payout_type", "standard"),
        "expected_return": entry.get("expected_return"),
        "expected_value": entry.get("expected_value"),
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
                "match_detail": _entry_leg_match_detail(prop),
                "settlement_evidence": _settlement_evidence_payload(
                    prop,
                    evidence_by_prop.get(int(prop.get("entry_prop_id") or 0)),
                ),
                "confidence": prop.get("confidence"),
                "clv": _clv_for_prop(
                    prop,
                    entry,
                    history=line_histories.get(_clv_history_key(prop), []) if line_histories is not None else None,
                    history_loaded=line_histories is not None,
                ),
            }
            for prop in props
        ],
    }


def _settlement_evidence_payload(prop: dict, audit: dict | None) -> dict:
    audit = audit or {}
    matched_dates = audit.get("matched_game_dates") or []
    return {
        "verification_status": audit.get("status") or prop.get("final_status") or "unknown",
        "provider": audit.get("provider") or prop.get("final_source") or "unmatched",
        "requested_player": audit.get("requested_player") or prop.get("player") or "",
        "matched_player": audit.get("matched_player") or "",
        "player_identity_id": audit.get("matched_identity_id") or prop.get("player_identity_id"),
        "requested_game": audit.get("requested_game") or prop.get("game") or "",
        "matched_game": audit.get("matched_game") or "",
        "requested_game_time": prop.get("game_time") or "",
        "matched_game_date": matched_dates[-1] if matched_dates else "",
        "actual": audit.get("actual") if audit.get("actual") is not None else prop.get("actual"),
        "result": audit.get("result") or prop.get("final_result") or "Pending",
        "reason_code": audit.get("reason_code") or "no_audit_record",
        "message": audit.get("message") or _entry_leg_match_detail(prop),
        "attempt_count": int(audit.get("attempt_count") or 0),
        "last_checked_at": audit.get("attempted_at") or "",
    }


def _entry_leg_match_detail(prop: dict) -> str:
    if prop.get("actual") is not None:
        return "Matched final stat row."
    missing = []
    if not prop.get("game"):
        missing.append("game")
    if not prop.get("game_time"):
        missing.append("game time")
    if not prop.get("final_source"):
        missing.append("provider source")
    if missing:
        return f"Missing {'/'.join(missing)} context for {prop.get('stat', 'stat')}."
    return f"No final stat matched for {prop.get('stat', 'stat')}."


def _platform_from_text(value: str) -> Platform:
    for platform in Platform:
        if platform.value.lower() == (value or "").lower():
            return platform
    return Platform.PRIZEPICKS


def _stat_from_text(value: str) -> StatType:
    return stat_type_from_text(value)


configure_player_router(
    PlayerDependencies(
        availability=lambda player, sport, team, game: _player_availability_payload(
            player,
            sport,
            team,
            game,
        ),
        detail=lambda player, platform, sport: build_player_detail_payload(
            player,
            platform,
            sport,
            fetch_props=lambda selected_platform, sport_filter: _fetch_props(
                selected_platform,
                sport_filter,
            ),
            build_detail=lambda selected_player, props: _player_detail_payload(
                selected_player,
                props,
            ),
        ),
        identity=lambda player, sport, team: build_player_identity_payload(
            player,
            sport,
            team,
        ),
        research=lambda player, stat, sport, platform, line: _player_research_payload(
            player,
            stat,
            None if sport == "All Sports" else sport.upper(),
            platform,
            line,
        ),
        research_evidence=lambda player, stat, sport, platform, game, include_expired: research_evidence_payload(
            player, stat, sport, platform, game, include_expired,
        ),
        line_movement=lambda player, stat, platform: build_player_line_movement_payload(
            player,
            stat,
            platform,
            active_line=lambda selected_player, selected_stat, selected_platform: _active_line_for_player_stat(
                selected_player,
                selected_stat,
                selected_platform,
            ),
            build_movement=lambda *args, **kwargs: _line_movement_payload(*args, **kwargs),
        ),
        hit_rate=lambda player, stat, line, projection, trending_count, sport: build_player_hit_rate_payload(
            player,
            stat,
            line,
            projection,
            trending_count,
            sport,
        ),
    )
)
app.include_router(player_router)


configure_upload_router(
    UploadDependencies(
        import_wizard=lambda: build_import_wizard_payload(
            lambda: _sportsbook_integrations_payload(),
        ),
        analyze=lambda payload: build_analyze_upload_payload(
            payload,
            decode=lambda content: _decode_uploaded_bytes(content),
            is_image=lambda value: _is_image_upload(value),
            analyze_image=lambda value, raw: _analyze_uploaded_image(value, raw),
            analyze_text=lambda value, raw: _analyze_uploaded_text_file(value, raw),
        ),
        import_history=lambda payload: {
            **_import_betting_history_payload(payload.payload, payload.source),
            "dashboard": get_dashboard(),
        },
    )
)
app.include_router(upload_router)


configure_bankroll_router(
    BankrollDependencies(
        update_bankroll=lambda payload: build_update_bankroll_payload(
            payload.amount,
            set_starting_bankroll=lambda amount: set_starting_bankroll(amount),
            dashboard=lambda amount: get_dashboard(amount),
        ),
        transactions=lambda: build_bankroll_transactions_payload(
            lambda: get_dashboard(),
        ),
        save_transaction=lambda payload: build_save_bankroll_transaction_payload(
            payload.transaction_type,
            payload.amount,
            payload.note,
            dashboard=lambda: get_dashboard(),
        ),
        strategy=lambda: {"strategy": _bankroll_strategy()},
        update_strategy=lambda payload: build_update_bankroll_strategy_payload(
            payload.model_dump(),
            save_setting=lambda key, value: SettingsRepository.set(key, value),
            serialize=lambda value: json.dumps(value),
            load_strategy=lambda: _bankroll_strategy(),
        ),
        loss_protection=lambda: _loss_protection_payload(),
        update_loss_protection=lambda payload: build_update_loss_protection_payload(
            payload.enabled,
            save_setting=lambda key, value: SettingsRepository.set(key, value),
            load_protection=lambda: _loss_protection_payload(),
        ),
        loss_review=lambda limit: _loss_review_payload(limit),
    )
)
app.include_router(bankroll_router)


configure_portfolio_router(
    PortfolioDependencies(
        dashboard=lambda: get_dashboard(),
        personal_profile=lambda: _personal_profile_payload(),
        bets=lambda limit, entry_limit: build_bets_payload(
            limit,
            entry_limit,
            load_bets=lambda: BetRepository().get_all(),
            load_entries=lambda: EntryRepository.all(),
            serialize_bet=lambda bet: _serialize_bet(bet),
            serialize_entry=lambda entry, evidence, histories: _serialize_bet_history_entry(entry, evidence, histories),
            load_settlement_evidence=lambda entry_ids: SettlementAuditRepository.latest_by_entry_ids(entry_ids),
            load_line_histories=lambda props: LineHistoryRepository.get_histories(props),
        ),
        save_bet=lambda payload: build_save_bet_payload(
            payload,
            potential_profit=lambda odds, wager: potential_profit(odds, wager),
            create_bet=lambda value, profit: Bet(
                sport=value.sport,
                game=value.game,
                description=value.description,
                odds=value.odds,
                wager=value.wager,
                result=value.result,
                profit=profit,
                platform=value.platform,
                stat_type=value.stat_type,
                win_probability=value.win_probability,
            ),
            save_bet=lambda bet: BetRepository().save(bet),
            serialize_bet=lambda bet: _serialize_bet(bet),
            dashboard=lambda: get_dashboard(),
        ),
        intelligence=lambda: _portfolio_intelligence_payload(),
        refresh_market=lambda: _refresh_portfolio_market_data_payload(),
    )
)
app.include_router(portfolio_router)


configure_advantage_router(
    AdvantageDependencies(
        advantage_center=lambda platform, sport: _advantage_center_payload(platform, sport),
    )
)
app.include_router(advantage_router)


configure_briefing_router(
    BriefingDependencies(
        briefing=lambda platform, sport, refresh, cached_only: _cached_daily_briefing_payload(
            platform,
            sport,
            refresh=refresh,
            cached_only=cached_only,
        ),
        new_scan=lambda platform, sport, trigger: _new_daily_scan(platform, sport, trigger),
        save_scan=lambda scan: _save_daily_scan_status(scan),
        run_scan=lambda platform, sport, scan_id, trigger, sync_result: _run_daily_briefing_scan(
            platform,
            sport,
            scan_id,
            trigger,
            sync_result,
        ),
        scan_status=lambda platform, sport: _daily_scan_status_payload(platform, sport),
    )
)
app.include_router(briefing_router)


configure_operations_router(
    OperationsDependencies(
        sync=lambda allow_estimates: build_sync_payload(
            allow_estimates,
            classify_economics=lambda: EntryRepository.classify_missing_economics(),
            import_final_stats_file=lambda: _import_file_if_configured(
                "EDGEIQ_FINAL_STATS_FILE",
                lambda payload, source: {
                    "imported": import_final_stats(payload, source),
                    "skipped": 0,
                },
            ),
            import_bet_history_file=lambda: _import_file_if_configured(
                "EDGEIQ_BET_HISTORY_FILE",
                _import_betting_history_payload,
            ),
            auto_check=lambda estimates: auto_check_entries(allow_estimates=estimates),
            refresh_live_stats=lambda: _refresh_live_stats(EntryRepository.pending()),
            dashboard=lambda: get_dashboard(),
        ),
        dnp_setting=lambda: {"mode": _dnp_mode()},
        update_dnp=lambda payload: build_update_dnp_payload(
            payload.mode,
            save_setting=lambda key, value: SettingsRepository.set(key, value),
        ),
        preferences=lambda: _user_preferences(),
        update_preferences=lambda payload: build_update_preferences_payload(
            payload,
            save_setting=lambda key, value: SettingsRepository.set(key, value),
            serialize=lambda value: json.dumps(value),
        ),
        provider_weights=lambda: {"weights": _provider_weights()},
        update_provider_weights=lambda payload: build_update_provider_weights_payload(
            payload,
            current_weights=lambda: _provider_weights(),
            save_setting=lambda key, value: SettingsRepository.set(key, value),
            serialize=lambda value: json.dumps(value),
        ),
        refresh_schedule=lambda: _refresh_schedule_payload(),
        update_refresh_schedule=lambda payload: build_update_refresh_schedule_payload(
            payload,
            save_setting=lambda key, value: SettingsRepository.set(key, value),
            serialize=lambda value: json.dumps(value),
        ),
        run_daily_refresh=lambda: _run_daily_refresh_now(),
        alert_delivery=lambda: _alert_delivery_settings(),
        update_alert_delivery=lambda payload: _update_alert_delivery_settings(payload),
        test_alert_delivery=lambda payload: _deliver_alert(payload.model_dump()),
        deploy_readiness=lambda: _deploy_readiness_payload(),
        runtime_status=lambda: _runtime_status_payload(),
        notifications=lambda: _notification_payload(),
        watchlist=lambda: build_watchlist_payload(
            load_items=lambda: _watchlist_items(),
            build_alerts=lambda items: _watchlist_alerts(items),
        ),
        save_watchlist=lambda payload: build_save_watchlist_payload(
            payload,
            item_id=lambda item: _watchlist_item_id(item),
            load_items=lambda: _watchlist_items(),
            save_items=lambda items: SettingsRepository.set("prop_watchlist", json.dumps(items)),
            build_alerts=lambda items: _watchlist_alerts(items),
        ),
        delete_watchlist=lambda item_id: build_delete_watchlist_payload(
            item_id,
            load_items=lambda: _watchlist_items(),
            save_items=lambda items: SettingsRepository.set("prop_watchlist", json.dumps(items)),
            build_alerts=lambda items: _watchlist_alerts(items),
        ),
        watchlist_alerts=lambda: build_watchlist_alerts_payload(
            build_alerts=lambda items: _watchlist_alerts(items),
        ),
        sportsbook_integrations=lambda: _sportsbook_integrations_payload(),
    )
)
app.include_router(operations_router)


configure_intelligence_router(
    IntelligenceDependencies(
        parlay_chat=lambda payload: build_parlay_chat_payload(
            payload,
            parse_request=lambda message, sport: _parse_parlay_request(message, sport),
            find_suggestions=lambda *args, **kwargs: _parlay_chat_suggestions(*args, **kwargs),
            serialize_suggestion=lambda suggestion: _serialize_suggestion(suggestion),
            local_response=lambda suggestions, request: local_parlay_response(suggestions, request),
            ai_response=lambda message, suggestions, request: _assistant_parlay_response(
                message,
                suggestions,
                request,
            ),
            local_model_version=EDGEIQ_LOCAL_MODEL_VERSION,
            local_model_card=lambda suggestions: local_model_card(suggestions),
        ),
        ai_status=lambda: build_ai_status_payload(
            os.getenv("OPENAI_API_KEY", ""),
            ollama_status=lambda: ollama_status(),
            openai_model=lambda: _openai_model(),
            openai_vision_model=lambda: _openai_vision_model(),
            local_model_version=EDGEIQ_LOCAL_MODEL_VERSION,
        ),
        entry_review=lambda payload: build_entry_review_payload(
            payload,
            entry_from_payload=lambda value: _entry_from_payload(value),
            analyze_entry=lambda entry: _entry_analysis(entry),
            fallback_review=lambda analysis: _fallback_entry_review(analysis),
            ai_review=lambda question, analysis: _assistant_entry_review(question, analysis),
            local_model_version=EDGEIQ_LOCAL_MODEL_VERSION,
        ),
        trending_games=lambda platform, sport, limit: build_trending_games_response(
            platform,
            sport,
            limit,
            fetch_props=lambda selected_platform, sport_filter: _fetch_props(
                selected_platform,
                sport_filter,
            ),
            top_props_by_sport=lambda props, per_sport_limit, sport_filter: _top_props_by_sport(
                props,
                per_sport_limit,
                sport_filter,
            ),
            build_games=lambda props, ranked_props, game_limit: _trending_games_payload(
                props,
                ranked_props,
                game_limit,
            ),
        ),
        game_context=lambda game, sport, platform: build_game_context_response(
            game,
            sport,
            platform,
            build_context=lambda selected_game, sport_filter, selected_platform: _game_context_payload(
                selected_game,
                sport_filter,
                selected_platform,
            ),
        ),
        ev_analysis=lambda payload: build_ev_analysis_payload(
            payload,
            bankroll=lambda: get_starting_bankroll(),
        ),
        projection_assist=lambda payload: build_projection_assist_payload(payload),
        copilot_query=lambda payload: build_copilot_query_payload(
            payload,
            player_research=lambda player, stat, sport, platform, line: _player_research_payload(
                player, stat, sport, platform, line,
            ),
            loss_review=lambda: _loss_review_payload(20),
            briefing=lambda platform, sport: _cached_daily_briefing_payload(
                platform, sport, refresh=False, cached_only=True,
            ),
            portfolio=lambda: _portfolio_intelligence_payload(),
        ),
        explain_recommendation=lambda payload: build_explain_recommendation_payload(payload),
        evaluate_model=lambda payload: build_model_evaluation_payload(payload),
    )
)
app.include_router(intelligence_router)


configure_recommendation_router(
    RecommendationDependencies(
        top_props=lambda platform, sport, limit: build_top_props_payload(
            platform,
            sport,
            limit,
            fetch_props=lambda selected_platform, sport_filter: _fetch_props(
                selected_platform,
                sport_filter,
            ),
            top_by_sport=lambda props, per_sport_limit, sport_filter: _top_props_by_sport(
                props,
                per_sport_limit,
                sport_filter,
            ),
        ),
        trending_props=lambda platform, sport, limit: build_cached_command_center_payload(
            platform,
            sport,
            False,
            cache=_TRENDING_PROPS_CACHE,
            lock=_TRENDING_PROPS_LOCK,
            ttl_seconds=PROP_FETCH_CACHE_SECONDS,
            canonical_platform=_canonical_platform,
            selected_platforms=_selected_platforms,
            fetcher_token=_platform_fetcher_cache_token,
            fetch_props_token=_fetch_props,
            payload_token=(build_trending_props_payload, min(int(limit), 15)),
            build_payload=lambda selected_platform, sport_filter: build_trending_props_payload(
                selected_platform,
                sport_filter or "All Sports",
                min(int(limit), 15),
                fetch_props=lambda requested_platform, requested_sport: _fetch_props(requested_platform, requested_sport),
                analyze_prop=lambda prop: _analyzed_feed_prop(prop),
                end_to_end_eligibility=lambda prop: _end_to_end_prop_eligibility(prop),
            ),
        ),
        confirmed_props=lambda platform, sport, limit: _confirmed_props_payload(
            platform,
            None if sport == "All Sports" else sport.upper(),
            limit,
        ),
        dashboard_parlay=lambda platform, sport: build_dashboard_parlay_payload(
            platform,
            sport,
            recommended_parlay=lambda selected_platform, sport_filter: _recommended_parlay(
                selected_platform,
                sport_filter,
            ),
            serialize_suggestion=lambda suggestion: _serialize_suggestion(suggestion),
        ),
        command_center=lambda platform, sport, refresh: build_cached_command_center_payload(
            platform,
            sport,
            refresh,
            cache=_COMMAND_CENTER_CACHE,
            lock=_COMMAND_CENTER_LOCK,
            ttl_seconds=COMMAND_CENTER_CACHE_SECONDS,
            canonical_platform=lambda value: _canonical_platform(value),
            selected_platforms=lambda value: _selected_platforms(value),
            fetcher_token=lambda value: _platform_fetcher_cache_token(value),
            fetch_props_token=id(_fetch_props),
            payload_token=id(_command_center_payload),
            build_payload=lambda selected_platform, sport_filter: _command_center_payload(
                selected_platform,
                sport_filter,
            ),
        ),
        opportunity_feed=lambda platform, sport, min_ev, limit, odds: _opportunity_feed_payload(
            platform,
            None if sport == "All Sports" else sport.upper(),
            min_ev,
            limit,
            odds,
        ),
        auto_paper=lambda payload: _auto_paper_calibration(payload),
        paper_calibration_status=lambda: _paper_calibration_status_payload(),
        entry_suggestions=lambda sport, platform, leg_count, avoid_prop_keys: build_entry_suggestions_payload(
            sport,
            platform,
            leg_count,
            canonical_platform=lambda value: _canonical_platform(value),
            entry_platforms=set(ENTRY_PLATFORMS),
            cached_briefing=lambda selected_platform, sport_filter: _cached_daily_briefing_payload(
                selected_platform,
                sport_filter,
                cached_only=True,
            ),
            fetch_props=lambda selected_platform, sport_filter: _fetch_props(
                selected_platform,
                sport_filter,
            ),
            props_by_platform=lambda selected_platform, props: _props_by_platform_from_props(
                selected_platform,
                props,
            ),
            mixed_risk=lambda props, selected_sport, platform_model: _mixed_risk_suggestions(
                props,
                selected_sport,
                platform_model,
            ),
            suggest=lambda *args, **kwargs: suggest_entries(*args, **kwargs),
            serialize_suggestion=lambda suggestion: _serialize_suggestion(suggestion),
            avoid_prop_keys=avoid_prop_keys,
        ),
        confirmed_suggestions=lambda sport, platform: build_confirmed_entry_suggestions_payload(
            sport,
            platform,
            confirmed_props=lambda selected_platform, sport_filter, limit: _confirmed_props_payload(
                selected_platform,
                sport_filter,
                limit,
            ),
            entry_platform=lambda value: _entry_platform_from_text(value),
            mixed_risk=lambda props, selected_sport, platform_model: _mixed_risk_suggestions(
                props,
                selected_sport,
                platform_model,
            ),
            serialize_suggestion=lambda suggestion: _serialize_suggestion(suggestion),
        ),
        crazy_six=lambda sport, platform: build_crazy_six_payload(
            sport,
            platform,
            selected_entry_platforms=lambda value: _selected_entry_platforms(value),
            fetch_platform_props=lambda value: _fetch_platform_props(value),
            feed_pool=lambda props, sport_filter: _crazy_six_feed_pool(props, sport_filter),
            analyze_prop=lambda prop: _analyzed_feed_prop(prop),
            confirm_prop=lambda prop, analyzed: _confirmed_prop_candidate(prop, analyzed),
            prop_pool=lambda props: _crazy_six_prop_pool(props),
            entry_platform=lambda value: _entry_platform_from_text(value),
            suggest=lambda *args, **kwargs: suggest_entries(*args, **kwargs),
            serialize_suggestion=lambda suggestion: _serialize_suggestion(suggestion),
            canonical_platform=lambda value: _canonical_platform(value),
            end_to_end_eligibility=lambda prop: _end_to_end_prop_eligibility(prop),
            parse_game_time=lambda value: _parse_game_time(value),
        ),
        optimizer=lambda platform, sport, min_legs, max_legs, limit, min_confidence, min_edge, max_same_team, exclude_correlated, apply_feedback: build_optimized_entries_payload(
            platform,
            sport,
            min_legs,
            max_legs,
            limit,
            min_confidence,
            min_edge,
            max_same_team,
            exclude_correlated,
            apply_feedback,
            optimize=lambda *args: _optimized_entries(*args),
            value_rank=lambda suggestions, selected_platform: build_portfolio_ranked_suggestions(
                _value_ranked_suggestions(suggestions, selected_platform),
                pending_entries=EntryRepository.pending(),
                strategy=_bankroll_strategy(),
                limit=limit,
            ),
            obstacles=lambda suggestions: _optimizer_obstacles(suggestions),
        ),
    )
)
app.include_router(recommendation_router)


configure_market_router(
    MarketDependencies(
        line_shop=lambda *args: _line_shop_payload(*args),
        sharp_consensus=lambda *args: _sharp_consensus_payload(*args),
        hedge_calculator=lambda payload: _hedge_calculator_payload(payload),
        middle_calculator=lambda payload: _middle_calculator_payload(payload),
        boost_analysis=lambda payload: _boost_analysis_payload(payload),
        ev_scanner=lambda *args: _ev_scanner_rows(*args),
        timing_alerts=lambda *args: _market_timing_alert_rows(*args),
        clv_report=lambda: _clv_report_payload(),
    )
)
app.include_router(market_router)

configure_provider_router(
    ProviderDependencies(
        data_health=lambda: _data_health_payload(),
        sleeper_status=lambda: sleeper.public_api_status(),
        verify_odds=lambda: _verify_odds_provider(),
    )
)
app.include_router(provider_router)

configure_results_router(
    ResultsDependencies(
        performance=lambda: _performance_payload(),
        create_backup=lambda: backup_database(),
        create_export=lambda: export_database(),
        backtest=lambda: _backtest_payload(),
        refresh_calibration=lambda: _refresh_calibration_data_payload(),
        model_health=lambda: _model_health_payload(),
        accuracy_lab=lambda: _accuracy_lab_payload(),
        data_integrity_repair=lambda dry_run: _data_integrity_repair_payload(dry_run),
    )
)
app.include_router(results_router)

configure_entry_router(
    EntryDependencies(
        analyze=lambda payload: build_analyze_entry_payload(
            payload,
            lambda props: _reject_combined_player_props(props),
            lambda value: _entry_from_payload(value, hydrate_provider=False),
            lambda entry, value: _entry_analysis(entry, value),
        ),
        payout_analysis=lambda payload: build_entry_payout_analysis_payload(
            payload,
            lambda props: _reject_combined_player_props(props),
            lambda direction: _normalize_direction(direction),
        ),
        placement_check=lambda payload: validated_call(
            payload.props,
            lambda props: _reject_combined_player_props(props),
            lambda: _placement_check(payload),
        ),
        platform_value_check=lambda payload: validated_call(
            payload.props,
            lambda props: _reject_combined_player_props(props),
            lambda: _platform_value_check(payload, live_refresh=True),
        ),
        handoff=lambda payload: validated_call(
            payload.props,
            lambda props: _reject_combined_player_props(props),
            lambda: _entry_handoff_payload(payload),
        ),
        share=lambda payload: validated_call(
            payload.props,
            lambda props: _reject_combined_player_props(props),
            lambda: _share_entry_payload(payload),
        ),
        shared_entry=lambda share_id: _shared_entry_payload(share_id),
        shared_entry_html=lambda share_id: _shared_entry_html(share_id),
        place=lambda payload: build_place_entry_payload(
            payload,
            reject_combined_props=lambda props: _reject_combined_player_props(props),
            loss_protection=lambda: _loss_protection_payload(),
            settlement_blocks=lambda value: _end_to_end_placement_blocks(value),
            generation_day_blocks=lambda value: _generated_entry_day_blocks(value),
            requires_verified_settlement=lambda value: _requires_verified_settlement(value),
            entry_from_payload=lambda value: _entry_from_payload(value),
            analyze_entry=lambda entry, value: _entry_analysis(entry, value),
            audit_snapshot=lambda entry, value, analysis, blocks: _entry_audit_snapshot(
                entry,
                value,
                analysis,
                blocks,
            ),
        ),
    )
)
app.include_router(entry_router)
app.include_router(experience_router)

configure_settlement_router(
    SettlementDependencies(
        grading_report=lambda compact: _grading_report_payload(compact=compact),
        settlement_audit=lambda limit: SettlementAuditRepository.queue(limit),
        pending_entries=lambda: build_pending_entries_payload(_serialize_pending),
        entry_progress=lambda auto_check, refresh_providers, market_detail: build_entry_progress_payload(
            auto_check=auto_check,
            refresh_providers=refresh_providers,
            market_detail=market_detail,
            auto_check_pending=lambda **kwargs: _auto_check_pending_entries(**kwargs),
            refresh_live_stats=lambda entries: _refresh_live_stats(entries),
            backfill_game_times=lambda entries: _backfill_missing_game_times(entries),
            serialize_progress=lambda entry, **kwargs: _entry_progress_payload(entry, **kwargs),
            entry_has_stat_data=lambda entry: _entry_has_stat_data(entry),
            settlement_status_key=SETTLEMENT_REFRESH_STATUS_KEY,
            safe_json_loads=lambda value: _safe_json_loads(value),
        ),
        settle_entry=lambda entry_id, payload: build_settle_entry_payload(
            entry_id,
            payload.result,
            payload.dnp_legs,
            _dnp_mode(),
            lambda: get_dashboard(),
        ),
        auto_check=lambda allow_estimates, refresh_providers: _auto_check_pending_entries(
            allow_estimates,
            refresh_providers=refresh_providers,
        ),
        backfill_final_stats=lambda allow_estimates: build_backfill_final_stats_payload(
            allow_estimates,
            lambda entry, **kwargs: _entry_leg_final_snapshots(entry, **kwargs),
        ),
        recheck_final_stats_preview=lambda: build_recheck_final_stats_preview_payload(
            entries_needing_refresh=lambda entries: _entries_needing_final_stat_refresh(entries),
            preview_leg=lambda entry, prop: _preview_entry_leg_repair(entry, prop),
        ),
        recheck_final_stats=lambda allow_estimates: build_recheck_final_stats_payload(
            allow_estimates=allow_estimates,
            unknown_leg_count=lambda entries: _unknown_entry_leg_count(entries),
            entries_needing_refresh=lambda entries: _entries_needing_final_stat_refresh(entries),
            refresh_final_stats=lambda entries: _refresh_final_stats(entries),
            backfill_settled_results=lambda entries: _backfill_settled_entry_leg_results(entries),
            auto_check_pending=lambda **kwargs: _auto_check_pending_entries(**kwargs),
            recheck_results=lambda entries, **kwargs: _recheck_entry_results(entries, **kwargs),
            quarantine_mismatched_evidence=lambda: _quarantine_mismatched_settlement_evidence(),
        ),
        classify_default_wagers=lambda: build_classify_default_wagers_payload(
            lambda: get_dashboard()
        ),
        import_final_stats=lambda payload: {
            "imported": import_final_stats(payload.payload, payload.source),
            "source": payload.source,
        },
    )
)
app.include_router(settlement_router)
