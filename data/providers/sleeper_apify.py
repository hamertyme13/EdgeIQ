"""Opt-in Sleeper Picks offer collection from the Zen Studio Apify actor."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from utils.stat_normalization import canonical_stat_label

ACTOR_URL = "https://api.apify.com/v2/acts/zen-studio~sleeper-player-props/run-sync-get-dataset-items"
CACHE_PATH = Path(".edgeiq_cache/providers/sleeper_apify.json")
CACHE_TTL_SECONDS = 3600
_LOCK = threading.Lock()
_LEAGUES = {"CFB": "NCAAF", "CBB": "NCAAM"}


def configured() -> bool:
    return os.getenv("EDGEIQ_SLEEPER_APIFY_ENABLED", "").strip() == "1" and bool(
        os.getenv("APIFY_TOKEN", "").strip() or os.getenv("APIFY_API_TOKEN", "").strip()
    )


def fetch_projections() -> list[dict]:
    if not configured():
        return []
    with _LOCK:
        cached = _read_cache()
        if cached and cached[0] <= CACHE_TTL_SECONDS:
            return cached[1]
        token = (os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN") or "").strip()
        leagues = [value.strip() for value in os.getenv("EDGEIQ_SLEEPER_APIFY_LEAGUES", "NFL").split(",") if value.strip()]
        try:
            response = requests.post(
                ACTOR_URL,
                params={"timeout": 45},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"leagues": leagues, "includeAlternateLines": False},
                timeout=55,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload if isinstance(payload, list) else payload.get("items", [])
            observed_at = datetime.now(UTC).isoformat()
            rows = [prop for item in items if (prop := normalize_offer(item, observed_at)) is not None]
            _write_cache(rows)
            return rows
        except (requests.RequestException, ValueError, TypeError):
            return cached[1] if cached and cached[0] <= CACHE_TTL_SECONDS else []


def normalize_offer(item: dict, observed_at: str) -> dict | None:
    if not isinstance(item, dict) or str(item.get("platform") or "").lower() != "sleeper":
        return None
    if (item.get("is_live") or item.get("in_game") or item.get("is_alternate")
            or item.get("status") != "active" or item.get("game_status") != "pre_game"):
        return None
    if str(item.get("season_type") or "").lower() in {"season_long", "season"}:
        return None
    player = str(item.get("player_name") or "").strip()
    stat = canonical_stat_label(str(item.get("stat") or "").replace("_", " "))
    league = str(item.get("league") or "").upper()
    league = _LEAGUES.get(league, league)
    home = str(item.get("home_team") or "").strip()
    away = str(item.get("away_team") or "").strip()
    offer_id = str(item.get("projection_id") or "").strip()
    game_id = str(item.get("game_id") or "").strip()
    start = str(item.get("game_start") or "").strip()
    try:
        line = float(item["line"])
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    if (not all((player, stat, home, away, offer_id, game_id))
            or start_dt.tzinfo is None or start_dt <= datetime.now(UTC)):
        return None
    return {
        "projection_id": offer_id,
        "provider_offer_id": offer_id,
        "provider_event_id": game_id,
        "player_id": str(item.get("player_id") or ""),
        "player": player,
        "team": str(item.get("player_team") or ""),
        "position": str(item.get("player_position") or ""),
        "league": league,
        "stat": stat,
        "line": line,
        "standard_line": line,
        "line_offer_type": "standard",
        "game": f"{away} @ {home}",
        "game_time": start,
        "status": "pre_game",
        "platform": "Sleeper",
        "provider_source": "Zen Studio Apify (third-party)",
        "offer_evidence_source": "Apify collector",
        "provider_offer_observed_at": observed_at,
        "provider_offer_verified_at": "",
        "payout_evidence": "unverified",
        "over_line_id": str(item.get("over_line_id") or ""),
        "under_line_id": str(item.get("under_line_id") or ""),
        "over_multiplier": item.get("over_multiplier"),
        "under_multiplier": item.get("under_multiplier"),
        "stale": False,
    }


def _read_cache() -> tuple[int, list[dict]] | None:
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        age = max(0, int(time.time() - float(payload["saved_at"])))
        rows = [row for row in payload["rows"] if isinstance(row, dict)]
        return age, rows
    except (OSError, KeyError, TypeError, ValueError):
        return None


def _write_cache(rows: list[dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"saved_at": time.time(), "rows": rows}), encoding="utf-8")
    temporary.replace(CACHE_PATH)
