"""
PrizePicks partner API provider.

Fetches live projections and normalizes them into a flat list of dicts.
"""

from __future__ import annotations

from typing import Optional

from data.providers.cache import get_json

_BASE = "https://partner-api.prizepicks.com"

_LEAGUE_MAP = {
    "NBA":    "NBA",
    "WNBA":   "WNBA",
    "NFL":    "NFL",
    "MLB":    "MLB",
    "MLBLIVE": "MLB",
    "NBASL":  "NBA",
    "NHL":    "NHL",
    "NCAAF":  "NCAAF",
    "CFB":    "NCAAF",
    "NCAAB":  "NCAAM",
    "CBB":    "NCAAM",
    "NCAAM":  "NCAAM",
    "NCAAW":  "NCAAW",
    "MLS":    "MLS",
    "EPL":    "EPL",
    "UCL":    "UCL",
    "SOCCER": "MLS",
    "TENNIS": "TENNIS",
    "ATP":    "TENNIS",
    "WTA":    "TENNIS",
    "PGA":    "PGA",
    "GOLF":   "PGA",
    "MMA":    "MMA",
    "UFC":    "MMA",
    "NASCAR": "NASCAR",
}

_SUPPORTED = set(_LEAGUE_MAP.keys())

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def _normalize_league(raw_league: str) -> str | None:
    """Return normalized sport name, or None if unsupported."""
    return _LEAGUE_MAP.get(raw_league.upper())


def _season_type(raw_league: str, attrs: dict, game_attrs: dict | None = None) -> str:
    game_attrs = game_attrs or {}
    text = " ".join([
        raw_league or "",
        str(attrs.get("league", "") or ""),
        str(attrs.get("description", "") or ""),
        str(attrs.get("game_type", "") or ""),
        str(game_attrs.get("description", "") or ""),
    ]).lower()
    if raw_league.upper() == "NBASL" or "summer league" in text:
        return "summer_league"
    if raw_league.upper() == "NFL":
        start_time = str(
            game_attrs.get("start_time")
            or attrs.get("start_time")
            or attrs.get("scheduled_at")
            or ""
        )
        if any(token in text for token in ("preseason", "hall of fame")) or _is_august_date(start_time):
            return "preseason"
    return "regular"


def _is_august_date(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) >= 7 and text[4:7] == "-08"


def _merge_player_attrs(current: dict, incoming: dict) -> dict:
    """Keep populated player fields when sideloaded duplicates are incomplete."""
    merged = dict(current)
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def fetch_projections(limit: int = 500) -> list[dict]:
    """
    Fetch today's PrizePicks Single-Stat projections for NBA/WNBA/NFL/MLB.

    Returns a list of dicts with keys:
        player, team, league, position, stat, line, game, status,
        trending_count, rank, image_url, projection_id
    """
    url = f"{_BASE}/projections?per_page={limit}&single_stat=true"

    cached = get_json(url, headers=_HEADERS, timeout=10, retries=1)
    data = cached.data

    # Build player lookup from included sideloaded data
    players: dict[str, dict] = {}
    games: dict[str, dict] = {}
    for item in data.get("included", []):
        if item.get("type") == "new_player":
            player_id = item["id"]
            players[player_id] = _merge_player_attrs(
                players.get(player_id, {}),
                item.get("attributes", {}),
            )
        elif item.get("type") == "game":
            games[item["id"]] = item.get("attributes", {})

    results: list[dict] = []

    for proj in data.get("data", []):
        attrs = proj.get("attributes", {})

        # Only pre-game single-stat projections
        if attrs.get("status") != "pre_game":
            continue
        if attrs.get("projection_type") != "Single Stat":
            continue

        rel = proj.get("relationships", {})
        player_id = rel.get("new_player", {}).get("data", {}).get("id")
        player_attrs = players.get(player_id, {})
        game_id = rel.get("game", {}).get("data", {}).get("id")
        game_attrs = games.get(game_id, {})

        raw_league = player_attrs.get("league", "")
        league = _normalize_league(raw_league)
        if league is None:
            continue

        results.append({
            "projection_id": proj.get("id"),
            "player_id":     player_id,
            "player":        player_attrs.get("display_name", "Unknown"),
            "team":          player_attrs.get("team", ""),
            "league":        league,
            "position":      player_attrs.get("position", ""),
            "stat":          attrs.get("stat_display_name", attrs.get("stat_type", "")),
            "line":          attrs.get("line_score"),
            "standard_line":  attrs.get("line_score") if str(attrs.get("odds_type", "standard")).lower() == "standard" else None,
            "flash_sale_line": attrs.get("flash_sale_line_score"),
            "odds_type":      str(attrs.get("odds_type", "standard") or "standard").lower(),
            "adjusted_odds":  bool(attrs.get("adjusted_odds")),
            "is_promo":      bool(attrs.get("is_promo")),
            "game":          _game_matchup(game_attrs) or attrs.get("description", ""),
            "game_time":      game_attrs.get("start_time") or attrs.get("start_time") or attrs.get("scheduled_at") or attrs.get("game_time") or attrs.get("commence_time") or "",
            "provider_game_id": str(game_attrs.get("external_game_id") or attrs.get("game_id") or game_id or ""),
            "season_type":    _season_type(raw_league, attrs, game_attrs),
            "status":        attrs.get("status", ""),
            "trending_count": attrs.get("trending_count", 0),
            "rank":          attrs.get("rank", 999),
            "image_url":     player_attrs.get("image_url", ""),
            "stale":         cached.stale,
            "cache_age_seconds": cached.age_seconds,
        })

    return results


def _game_matchup(game_attrs: dict) -> str:
    teams = (game_attrs.get("metadata") or {}).get("game_info", {}).get("teams", {})
    away = str((teams.get("away") or {}).get("abbreviation") or "").strip()
    home = str((teams.get("home") or {}).get("abbreviation") or "").strip()
    return f"{away} @ {home}" if away and home else ""


def top_props(n: int = 25, sport: str | None = None) -> list[dict]:
    """
    Return the top-N props sorted by trending count.

    Args:
        n:     Number of props to return.
        sport: Optional sport filter ('NBA', 'WNBA', 'NFL', 'MLB').
               If None, returns across all supported sports.
    """
    try:
        props = fetch_projections(limit=1000)
    except RuntimeError:
        return []

    if sport:
        props = [p for p in props if p["league"] == sport.upper()]

    props.sort(key=lambda p: p["trending_count"], reverse=True)

    return props[:n]
