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


def _normalize_league(raw_league: str) -> Optional[str]:
    """Return normalized sport name, or None if unsupported."""
    return _LEAGUE_MAP.get(raw_league.upper())


def _season_type(raw_league: str, attrs: dict) -> str:
    text = " ".join([
        raw_league or "",
        str(attrs.get("league", "") or ""),
        str(attrs.get("description", "") or ""),
        str(attrs.get("game_type", "") or ""),
    ]).lower()
    if raw_league.upper() == "NBASL" or "summer league" in text:
        return "summer_league"
    return "regular"


def fetch_projections(limit: int = 500) -> list[dict]:
    """
    Fetch today's PrizePicks Single-Stat projections for NBA/WNBA/NFL/MLB.

    Returns a list of dicts with keys:
        player, team, league, position, stat, line, game, status,
        trending_count, rank, image_url, projection_id
    """
    url = f"{_BASE}/projections?per_page={limit}&single_stat=true"

    cached = get_json(url, headers=_HEADERS, timeout=15)
    data = cached.data

    # Build player lookup from included sideloaded data
    players: dict[str, dict] = {}
    for item in data.get("included", []):
        if item.get("type") == "new_player":
            players[item["id"]] = item.get("attributes", {})

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

        raw_league = player_attrs.get("league", "")
        league = _normalize_league(raw_league)
        if league is None:
            continue

        results.append({
            "projection_id": proj.get("id"),
            "player":        player_attrs.get("display_name", "Unknown"),
            "team":          player_attrs.get("team", ""),
            "league":        league,
            "position":      player_attrs.get("position", ""),
            "stat":          attrs.get("stat_display_name", attrs.get("stat_type", "")),
            "line":          attrs.get("line_score"),
            "game":          attrs.get("description", ""),
            "game_time":      attrs.get("start_time") or attrs.get("scheduled_at") or attrs.get("game_time") or attrs.get("commence_time") or "",
            "season_type":    _season_type(raw_league, attrs),
            "status":        attrs.get("status", ""),
            "trending_count": attrs.get("trending_count", 0),
            "rank":          attrs.get("rank", 999),
            "image_url":     player_attrs.get("image_url", ""),
            "stale":         cached.stale,
            "cache_age_seconds": cached.age_seconds,
        })

    return results


def top_props(n: int = 25, sport: Optional[str] = None) -> list[dict]:
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
