"""Configurable prop-feed adapter for platforms without stable public APIs."""

from __future__ import annotations

import csv
import json
import os
from io import StringIO
from pathlib import Path
from typing import Any

import requests

from data.providers.cache import get_json


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json,text/csv,*/*",
}


def fetch_configured_props(platform: str, env_prefix: str) -> list[dict]:
    """Load props from an env-configured URL or local file.

    Supported env vars:
      - EDGEIQ_<PREFIX>_PROPS_URL
      - EDGEIQ_<PREFIX>_PROPS_FILE
      - EDGEIQ_<PREFIX>_API_KEY, sent as Bearer auth for URL fetches

    Rows can be CSV or JSON. JSON may be a list or a dict containing one of
    props, projections, lines, data, or items.
    """
    url = os.getenv(f"EDGEIQ_{env_prefix}_PROPS_URL", "").strip()
    file_path = os.getenv(f"EDGEIQ_{env_prefix}_PROPS_FILE", "").strip()

    if url:
        payload = _load_url(url, env_prefix)
    elif file_path:
        payload = _load_file(file_path)
    else:
        return []

    return normalize_props(payload, platform)


def normalize_props(payload: Any, platform: str) -> list[dict]:
    rows = _extract_rows(payload)
    return [
        prop
        for prop in (_normalize_row(row, platform, index) for index, row in enumerate(rows))
        if prop is not None
    ]


def _load_url(url: str, env_prefix: str) -> Any:
    api_key = os.getenv(f"EDGEIQ_{env_prefix}_API_KEY", "").strip()
    headers = dict(_HEADERS)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if _looks_json(url):
        return get_json(url, headers=headers, timeout=15, ttl_seconds=300).data

    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    text = response.text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _load_file(file_path: str) -> Any:
    source = Path(file_path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json" or text.strip().startswith(("[", "{")):
        return json.loads(text)
    return text


def _extract_rows(payload: Any) -> list[dict]:
    if isinstance(payload, str):
        return _csv_rows(payload)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("props", "projections", "lines", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                nested = _extract_rows(value)
                if nested:
                    return nested
    return []


def _csv_rows(text: str) -> list[dict]:
    reader = csv.DictReader(StringIO(text.strip()))
    return [dict(row) for row in reader]


def _normalize_row(row: dict, platform: str, index: int) -> dict | None:
    player = _first_value(row, "player", "player_name", "name", "athlete", "athlete_name")
    stat = _first_value(row, "stat", "stat_type", "market", "market_name", "category")
    line = _float_value(row, "line", "line_score", "stat_value", "value", "projection", "pick_line")
    if not player or not stat or line is None:
        return None

    league = _normalize_sport(_first_value(row, "league", "sport", "sport_id", "league_name"))
    trending = _int_value(row, "trending_count", "popular_count", "rank_score", "popularity")
    rank = _int_value(row, "rank", "display_order", "sort_order")
    if trending == 0 and rank > 0:
        trending = max(1, 1_000_000 - rank)

    return {
        "projection_id": _first_value(row, "projection_id", "id", "line_id") or f"{platform.lower()}-{index}",
        "player": player,
        "team": _first_value(row, "team", "team_abbr", "team_id", "team_abbreviation"),
        "league": league,
        "position": _first_value(row, "position", "position_name"),
        "stat": stat,
        "line": line,
        "direction": _first_value(row, "direction", "pick", "side", "over_under"),
        "game": _first_value(row, "game", "matchup", "event", "opponent", "description"),
        "status": _first_value(row, "status") or "pre_game",
        "trending_count": trending,
        "rank": rank or index + 1,
        "image_url": _first_value(row, "image_url", "headshot", "photo"),
        "platform": platform,
    }


def _first_value(row: dict, *keys: str) -> str:
    normalized = {_clean_key(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(_clean_key(key))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _float_value(row: dict, *keys: str) -> float | None:
    value = _first_value(row, *keys)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(row: dict, *keys: str) -> int:
    value = _first_value(row, *keys)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _normalize_sport(value: str) -> str:
    normalized = value.strip().upper()
    aliases = {
        "BASKETBALL": "NBA",
        "WOMENS_BASKETBALL": "WNBA",
        "WOMEN'S BASKETBALL": "WNBA",
        "BASEBALL": "MLB",
        "FOOTBALL": "NFL",
        "HOCKEY": "NHL",
        "COLLEGE FOOTBALL": "NCAAF",
        "COLLEGE_FOOTBALL": "NCAAF",
        "CFB": "NCAAF",
        "COLLEGE BASKETBALL": "NCAAM",
        "COLLEGE_BASKETBALL": "NCAAM",
        "CBB": "NCAAM",
        "WOMENS COLLEGE BASKETBALL": "NCAAW",
        "WOMEN'S COLLEGE BASKETBALL": "NCAAW",
        "SOCCER": "MLS",
        "PREMIER LEAGUE": "EPL",
        "CHAMPIONS LEAGUE": "UCL",
        "ATP": "TENNIS",
        "WTA": "TENNIS",
        "GOLF": "PGA",
        "UFC": "MMA",
    }
    return aliases.get(normalized, normalized)


def _clean_key(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _looks_json(url: str) -> bool:
    return ".json" in url.lower() or "format=json" in url.lower()
