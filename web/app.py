from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import data.providers.prizepicks as prizepicks
import data.providers.underdog as underdog
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
from repository.repositories.line_history_repository import LineHistoryRepository
from data.providers.final_stats import find_actual_stat, import_final_stats
from services.betting import potential_profit
from services.dashboard import get_dashboard, get_starting_bankroll, set_starting_bankroll


STATIC_DIR = Path(__file__).parent / "static"
SUPPORTED_SPORTS = ("WNBA", "NBA", "NFL", "MLB")


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


class FinalStatsPayload(BaseModel):
    payload: str
    source: str = "manual"


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
    platform: Literal["PrizePicks", "Underdog", "Both"] = "PrizePicks",
    sport: str = "All Sports",
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    suggestion = _recommended_parlay(platform, sport_filter)
    return {
        "suggestion": _serialize_suggestion(suggestion) if suggestion else None,
        "platform": platform,
        "sport": sport,
    }


@app.get("/api/games/trending")
def trending_games(
    platform: Literal["PrizePicks", "Underdog", "Both"] = "PrizePicks",
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
    wager: float = Field(default=0.0, ge=0)
    multiplier: float = Field(default=1.0, ge=1)
    props: list[PropPayload]


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
    result: Literal["Win", "Loss", "Push"]


@app.post("/api/entries/{entry_id}/settle")
def settle_entry(entry_id: int, payload: SettlePayload) -> dict:
    EntryRepository.settle(entry_id, payload.result)
    return {"id": entry_id, "result": payload.result, "status": "Settled", "dashboard": get_dashboard()}


@app.get("/api/entries/suggestions")
def entry_suggestions(
    sport: str = "WNBA",
    platform: Literal["PrizePicks", "Underdog"] = "PrizePicks",
    leg_count: int = 2,
) -> dict:
    if leg_count < 2 or leg_count > 5:
        raise HTTPException(status_code=400, detail="Leg count must be between 2 and 5.")
    platform_model = _platform_from_text(platform)
    raw_props = prizepicks.fetch_projections(limit=1000) if platform_model == Platform.PRIZEPICKS else underdog.fetch_projections()
    suggestions = suggest_entries(raw_props, sport, platform_model, leg_count=leg_count)
    return {"suggestions": [_serialize_suggestion(suggestion) for suggestion in suggestions]}


@app.get("/api/entries/optimizer")
def optimize_entries(
    platform: Literal["PrizePicks", "Underdog", "Both"] = "PrizePicks",
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
    platform: Literal["PrizePicks", "Underdog", "Both"] = "Both",
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
    platform: Literal["PrizePicks", "Underdog"] = "PrizePicks",
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
    checks = [_check_entry_result(entry, allow_estimates) for entry in EntryRepository.pending()]
    settled = [check for check in checks if check["settled"]]
    return {
        "checked": len(checks),
        "settled": len(settled),
        "entries": checks,
        "estimated": any(check["source"] == "projection_estimate" for check in checks),
    }


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
    _record_line_snapshots(props)
    return props


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
        ranked_prop["sport_rank"] = len(sport_props) + 1
        sport_props.append(ranked_prop)

    ordered_sports = sorted(grouped)
    return [prop for sport in ordered_sports for prop in grouped[sport]]


def _with_sport_rank(props: list[dict], sport: str) -> list[dict]:
    ranked = []
    for index, prop in enumerate(props, start=1):
        ranked_prop = dict(prop)
        ranked_prop["sport_rank"] = index
        ranked_prop["league"] = ranked_prop.get("league") or sport
        ranked.append(ranked_prop)
    return ranked


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
    platform_props: list[tuple[Platform, list[dict]]] = []
    if platform in ("PrizePicks", "Both"):
        props = prizepicks.fetch_projections(limit=1000)
        for prop in props:
            prop.setdefault("platform", "PrizePicks")
        platform_props.append((Platform.PRIZEPICKS, props))
    if platform in ("Underdog", "Both"):
        platform_props.append((Platform.UNDERDOG, underdog.fetch_projections()))

    best = None
    for platform_model, props in platform_props:
        sports = [sport_filter] if sport_filter else sorted({prop.get("league", "").upper() for prop in props if prop.get("league")})
        for sport in sports:
            suggestions = suggest_entries(props, sport, platform_model, limit=1, leg_count=3)
            if suggestions and (best is None or suggestions[0].score > best.score):
                best = suggestions[0]
    return best


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


def _props_by_platform(platform: str) -> list[tuple[Platform, list[dict]]]:
    platforms: list[tuple[Platform, list[dict]]] = []
    if platform in ("PrizePicks", "Both"):
        props = prizepicks.fetch_projections(limit=1000)
        for prop in props:
            prop.setdefault("platform", "PrizePicks")
        platforms.append((Platform.PRIZEPICKS, props))
    if platform in ("Underdog", "Both"):
        props = underdog.fetch_projections()
        for prop in props:
            prop.setdefault("platform", "Underdog")
        platforms.append((Platform.UNDERDOG, props))
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


def _check_entry_result(entry: dict, allow_estimates: bool) -> dict:
    legs = []
    unknown = False
    source = "actual_provider"

    for prop in entry["props"]:
        actual = _actual_stat_for_prop(prop)
        leg_source = "actual_provider"
        if actual is None and allow_estimates:
            actual = prop.get("projection")
            leg_source = "projection_estimate"
        if actual is None:
            unknown = True
            leg_result = "Unknown"
        elif actual > prop["line"]:
            leg_result = "Win"
        elif actual < prop["line"]:
            leg_result = "Loss"
        else:
            leg_result = "Push"
        if leg_source == "projection_estimate":
            source = "projection_estimate"
        legs.append({**prop, "actual": actual, "result": leg_result, "source": leg_source})

    if unknown:
        return {
            "id": entry["id"],
            "settled": False,
            "result": "Unknown",
            "source": "unavailable",
            "message": "Final stat data is not available yet.",
            "legs": legs,
        }

    if any(leg["result"] == "Loss" for leg in legs):
        result = "Loss"
    elif any(leg["result"] == "Push" for leg in legs):
        result = "Push"
    else:
        result = "Win"

    EntryRepository.settle(entry["id"], result)
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
        actual = _actual_stat_for_prop(prop)
        if actual is None:
            status = "Pending"
            projected = _projected_leg_status(prop)
            if projected == "Win":
                projected_wins += 1
            elif projected == "Loss":
                projected_losses += 1
            elif projected == "Push":
                projected_pushes += 1
        else:
            status = _leg_result(actual, prop["line"])
            projected = status
            completed += 1
            source = "actual_provider"

        legs.append({
            **prop,
            "actual": actual,
            "status": status,
            "projected_status": projected,
            "progress_text": _leg_progress_text(prop, actual),
        })

    if completed == len(legs) and legs:
        projected_result = _entry_result_from_leg_statuses([leg["status"] for leg in legs])
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
        "projected_result": projected_result,
        "projected_wins": projected_wins,
        "projected_losses": projected_losses,
        "projected_pushes": projected_pushes,
        "legs": legs,
    }


def _leg_result(actual: float, line: float) -> str:
    if actual > line:
        return "Win"
    if actual < line:
        return "Loss"
    return "Push"


def _projected_leg_status(prop: dict) -> str:
    projection = prop.get("projection")
    if projection is None:
        return "Pending"
    return _leg_result(projection, prop["line"])


def _entry_result_from_leg_statuses(statuses: list[str]) -> str:
    if any(status == "Loss" for status in statuses):
        return "Loss"
    if any(status == "Pending" for status in statuses):
        return "In Progress"
    if any(status == "Push" for status in statuses):
        return "Push"
    return "Win" if statuses else "In Progress"


def _leg_progress_text(prop: dict, actual: float | None) -> str:
    value = actual if actual is not None else prop.get("projection")
    label = "Actual" if actual is not None else "Projection"
    if value is None:
        return "Waiting for stat data"
    return f"{label} {value:g} vs line {prop['line']:g}"


def _actual_stat_for_prop(prop: dict) -> float | None:
    return find_actual_stat(prop)


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
        "leg_count": suggestion.entry.prop_count,
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
