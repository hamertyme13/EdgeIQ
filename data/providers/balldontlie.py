"""Ball Don't Lie provider for stats and optional prop feeds."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from utils.entity_normalization import canonical_person_key

from data.providers.cache import get_json
from data.providers.generic_props import normalize_props


_BASE = "https://api.balldontlie.io"
_SPORT_PREFIX = {
    "NBA": "nba/v1",
    "MLB": "mlb/v1",
    "NFL": "nfl/v1",
}


def fetch_props(sport: str | None = None) -> list[dict]:
    url = os.getenv("BALLDONTLIE_PROPS_URL", "").strip()
    if not url:
        return []
    try:
        data = get_json(url, headers=_headers(), timeout=15, ttl_seconds=300).data
    except RuntimeError:
        return []
    props = normalize_props(data, "Ball Don't Lie")
    if sport:
        props = [prop for prop in props if prop.get("league", "").upper() == sport.upper()]
    return props


def fetch_player_stats(player: str, stat: str, sport: str, target_date: date | None = None) -> list[dict]:
    sport_key = sport.upper()
    prefix = _SPORT_PREFIX.get(sport_key)
    if prefix is None or not os.getenv("BALLDONTLIE_API_KEY", "").strip():
        return []

    configured = os.getenv("BALLDONTLIE_STATS_URL", "").strip()
    url = configured or f"{_BASE}/{prefix}/stats"
    if target_date and "?" not in url:
        url = f"{url}?dates[]={target_date.isoformat()}"
    try:
        data = get_json(url, headers=_headers(), timeout=15, ttl_seconds=1800).data
    except RuntimeError:
        return []
    return _extract_player_stat_rows(data, player, stat, sport_key)


def stat_signal(player: str, stat: str, sport: str) -> dict | None:
    rows = fetch_player_stats(player, stat, sport)
    if not rows:
        return None
    values = [float(row["actual"]) for row in rows if row.get("actual") is not None]
    if not values:
        return None
    return {
        "player": player,
        "stat": stat,
        "sport": sport.upper(),
        "sample_size": len(values),
        "average": round(sum(values) / len(values), 2),
        "source": "balldontlie",
    }


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    api_key = os.getenv("BALLDONTLIE_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = api_key
    return headers


def _extract_player_stat_rows(data: Any, player: str, stat: str, sport: str) -> list[dict]:
    rows = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        player_name = _player_name(row)
        needle = canonical_person_key(player)
        candidate = canonical_person_key(player_name)
        if needle not in candidate:
            continue
        value = _stat_value(row, stat)
        if value is None:
            continue
        results.append({
            "player": player_name,
            "sport": sport,
            "stat": stat,
            "actual": value,
            "source": "balldontlie",
        })
    return results


def _player_name(row: dict) -> str:
    player = row.get("player") or row.get("athlete") or {}
    if isinstance(player, dict):
        return (
            player.get("full_name")
            or f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            or player.get("name", "")
        )
    return str(player or row.get("player_name", ""))


def _stat_value(row: dict, stat: str) -> float | None:
    normalized = stat.lower()
    keys = {
        "points": ("pts", "points"),
        "rebounds": ("reb", "rebounds"),
        "assists": ("ast", "assists"),
        "steals": ("stl", "steals"),
        "blocks": ("blk", "blocks"),
        "3-pointers made": ("fg3m", "three_pointers_made"),
        "hits": ("hits", "h"),
        "runs": ("runs", "r"),
        "rbis": ("rbi", "rbis"),
        "ks": ("strikeouts", "so"),
    }
    if "pra" in normalized:
        values = [_value(row, key) for key in ("pts", "reb", "ast", "points", "rebounds", "assists")]
        if values[:3] and all(value is not None for value in values[:3]):
            return sum(values[:3])
        if all(value is not None for value in values[3:]):
            return sum(values[3:])
        return None
    for label, candidates in keys.items():
        if label in normalized:
            return next((value for value in (_value(row, key) for key in candidates) if value is not None), None)
    return None


def _value(row: dict, key: str) -> float | None:
    try:
        value = row.get(key)
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
