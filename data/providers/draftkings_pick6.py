"""DraftKings Pick6 offers supplied by the Apify actor marketplace."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests

ACTOR_ID = "zen-studio~draftkings-pick6-player-props"
ACTOR_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
CACHE_PATH = Path(".edgeiq_cache/providers/draftkings_pick6.json")
CACHE_TTL_SECONDS = 3600
SUPPORTED_LEAGUES = ("MLB", "NBA", "NHL", "Soccer", "PGA", "UFC", "CS", "LOL", "VAL", "COD", "NASCAR")

_LOCK = threading.Lock()
_LEAGUE_MAP = {
    "MLB": "MLB", "NBA": "NBA", "NHL": "NHL", "SOCCER": "MLS",
    "MLS": "MLS", "EPL": "EPL", "UCL": "UCL", "PGA": "PGA",
    "UFC": "MMA", "MMA": "MMA", "CS": "CS2", "CS2": "CS2",
    "LOL": "LOL", "VAL": "VALORANT", "VALORANT": "VALORANT",
    "COD": "COD", "NASCAR": "NASCAR",
}


def configured() -> bool:
    return bool(_token())


def fetch_projections(*, refresh: bool = False) -> list[dict]:
    """Return normalized offers, minimizing billable actor executions."""
    with _LOCK:
        cached = _read_cache()
        if cached and (not refresh or cached[0] <= CACHE_TTL_SECONDS):
            return [dict(row) for row in cached[1]]
        token = _token()
        if not token:
            return [dict(row) for row in cached[1]] if cached else []

        response = requests.post(
            ACTOR_URL,
            params={"timeout": 45},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"leagues": ["All"], "includeAlternateLines": False},
            timeout=55,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload if isinstance(payload, list) else payload.get("items", [])
        rows = [row for item in items if (row := normalize_offer(item)) is not None]
        _write_cache(rows)
        return rows


def normalize_offer(item: dict[str, Any]) -> dict | None:
    player = _text(item, "playerName", "player_name", "player", "name")
    stat = _text(item, "statType", "stat_type", "stat", "market", "category")
    line = _number(item, "line", "lineValue", "line_score", "value", "points")
    league_raw = _text(item, "league", "sport", "competition").upper()
    league = _LEAGUE_MAP.get(league_raw, league_raw)
    if not player or not stat or line is None or not league:
        return None

    alternate = bool(item.get("isAlternateLine") or item.get("alternateLine") or item.get("is_alternate"))
    event = _mapping(item, "event", "game", "contest", "matchup")
    away_team = _nested_text(event, "awayTeam", "away_team", "away")
    home_team = _nested_text(event, "homeTeam", "home_team", "home")
    game = _text(item, "matchup", "game", "gameName", "eventName")
    if not game:
        game = _text(event, "matchup", "name", "shortName", "displayName")
    if not game and away_team and home_team:
        game = f"{away_team} @ {home_team}"
    game_time = _text(item, "gameTime", "startTime", "start_time", "scheduledAt", "date")
    if not game_time:
        game_time = _text(event, "gameTime", "startTime", "start_time", "scheduledAt", "date", "commenceTime")
    provider_player_id = _text(item, "playerId", "player_id", "participantId")
    projection_id = _text(item, "offerId", "projectionId", "id")
    return {
        "projection_id": projection_id,
        "provider_player_id": provider_player_id,
        "player_id": provider_player_id,
        "player": player,
        "team": _text(item, "team", "teamAbbreviation", "team_name") or _nested_text(item, "team"),
        "league": league,
        "position": _text(item, "position"),
        "stat": stat,
        "line": line,
        "standard_line": None if alternate else line,
        "baseline_line": line,
        "line_offer_type": "alternate" if alternate else "standard",
        "adjusted_line": alternate,
        "game": game,
        "game_time": game_time,
        "provider_game_id": _text(item, "gameId", "eventId", "event_id") or _text(event, "id", "eventId", "gameId"),
        "provider_event_id": _text(item, "gameId", "eventId", "event_id") or _text(event, "id", "eventId", "gameId"),
        "provider_offer_id": projection_id,
        "status": "pre_game",
        "platform": "DraftKings Pick6",
        "provider": "DraftKings Pick6 via Apify",
        "provider_payout": _number(item, "payout", "multiplier", "payoutMultiplier"),
        "trending_count": int(_number(item, "trendingCount", "popularity", "rank") or 0),
        "source_payload": item,
    }


def cache_status() -> dict[str, Any]:
    cached = _read_cache()
    return {
        "configured": configured(),
        "cached": bool(cached),
        "age_seconds": cached[0] if cached else None,
        "row_count": len(cached[1]) if cached else 0,
        "fresh": bool(cached and cached[0] <= CACHE_TTL_SECONDS),
        "supported_leagues": list(SUPPORTED_LEAGUES),
    }


def _token() -> str:
    return (os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN") or "").strip()


def _read_cache() -> tuple[int, list[dict]] | None:
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        age = max(0, int(time.time() - float(payload["saved_at"])))
        return age, list(payload.get("rows") or [])
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_cache(rows: list[dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"saved_at": time.time(), "rows": rows}), encoding="utf-8")
    temporary.replace(CACHE_PATH)


def _text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            if isinstance(value, dict):
                value = value.get("name") or value.get("displayName") or value.get("label")
            if value not in (None, ""):
                return str(value).strip()
    return ""


def _number(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("value")
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _mapping(item: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _nested_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            text = _text(value, "abbreviation", "shortName", "displayName", "name", "label")
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""
