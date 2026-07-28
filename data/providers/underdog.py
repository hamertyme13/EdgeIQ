"""
Underdog Fantasy over/under lines provider.

Fetches live player prop lines and normalizes them into the same flat dict
format used by data/providers/prizepicks.py, so the dashboard can merge
results from both platforms seamlessly.

Normalized dict keys:
    projection_id, player, team, league, position,
    stat, line, game, status, trending_count, rank, image_url, platform
"""

from __future__ import annotations

from typing import Optional

from data.providers.cache import get_json

_BASE = "https://api.underdogfantasy.com/beta/v5"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Underdog sport_id → normalized league name
_LEAGUE_MAP = {
    "NBA":        "NBA",
    "BASKETBALL": "NBA",   # Underdog uses BASKETBALL for NBA regular games
    "WNBA":       "WNBA",
    "NFL":        "NFL",
    "MLB":        "MLB",
    "NHL":        "NHL",
    "HOCKEY":     "NHL",
    "NCAAF":      "NCAAF",
    "COLLEGE_FOOTBALL": "NCAAF",
    "NCAAB":      "NCAAM",
    "NCAAM":      "NCAAM",
    "COLLEGE_BASKETBALL": "NCAAM",
    "NCAAW":      "NCAAW",
    "MLS":        "MLS",
    "SOCCER":     "MLS",
    "EPL":        "EPL",
    "UCL":        "UCL",
    "TENNIS":     "TENNIS",
    "PGA":        "PGA",
    "GOLF":       "PGA",
    "MMA":        "MMA",
    "UFC":        "MMA",
    "NASCAR":     "NASCAR",
}

_SUPPORTED = set(_LEAGUE_MAP.keys())


def _normalize_league(raw: str) -> Optional[str]:
    return _LEAGUE_MAP.get(raw.upper())


def _season_type(raw_sport: str, game: dict, app_stat: dict) -> str:
    text = " ".join([
        raw_sport or "",
        str(game.get("title", "") or ""),
        str(game.get("short_title", "") or ""),
        str(game.get("abbreviated_title", "") or ""),
        str(app_stat.get("display_stat", "") or ""),
    ]).lower()
    if str(app_stat.get("display_stat", "") or "").lower().startswith("season "):
        return "season_long"
    if "summer league" in text or raw_sport.upper() in {"NBASL", "NBA_SUMMER_LEAGUE"}:
        return "summer_league"
    return "regular"


def _string_id(value: object) -> str:
    return str(value if value is not None else "").strip()


def _first_value(*values: object) -> object:
    return next((value for value in values if value not in (None, "")), "")


def _nested_id(value: object) -> str:
    if isinstance(value, dict):
        return _string_id(value.get("id"))
    return _string_id(value)


def _game_time(*sources: dict) -> str:
    keys = ("scheduled_at", "starts_at", "start_time", "game_time", "commence_time")
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value:
                return str(value)
    return ""


def fetch_projections() -> list[dict]:
    """
    Fetch active Underdog over/under lines for NBA/WNBA/NFL/MLB.

    Returns a list of normalized dicts matching the PrizePicks schema
    (plus a 'platform' key set to 'Underdog').
    """
    url = f"{_BASE}/over_under_lines"

    cached = get_json(url, headers=_HEADERS, timeout=15)
    data = cached.data

    # Build lookup indexes from sideloaded data
    players = {
        _string_id(player.get("id")): player
        for player in data.get("players", [])
        if _string_id(player.get("id"))
    }
    appearances = {
        _string_id(appearance.get("id")): appearance
        for appearance in data.get("appearances", [])
        if _string_id(appearance.get("id"))
    }

    games: dict[str, dict] = {}
    for g in data.get("games", []):
        games[_string_id(g.get("id"))] = g
    for g in data.get("solo_games", []):
        games[_string_id(g.get("id"))] = g

    results: list[dict] = []

    for line in data.get("over_under_lines", []):
        # Only active lines
        if line.get("status") != "active":
            continue

        ou        = line.get("over_under", {})
        app_stat  = ou.get("appearance_stat", {})
        app_id    = _string_id(_first_value(app_stat.get("appearance_id"), app_stat.get("appearance")))
        app       = appearances.get(app_id, {})
        player_id = _string_id(_first_value(
            app.get("player_id"),
            app_stat.get("player_id"),
            _nested_id(app.get("player")),
        ))
        player    = players.get(player_id, {})

        raw_sport = str(_first_value(
            player.get("sport_id"),
            app.get("sport_id"),
            ou.get("sport_id"),
            line.get("sport_id"),
        ))
        league    = _normalize_league(raw_sport)
        if league is None:
            continue

        # Reconstruct game matchup string from game title
        match_id = _string_id(_first_value(
            app.get("match_id"),
            app.get("game_id"),
            app_stat.get("match_id"),
            app_stat.get("game_id"),
            _nested_id(app.get("match")),
            _nested_id(app.get("game")),
        ))
        game      = games.get(match_id, {})
        matchup = str(_first_value(
            game.get("abbreviated_title"),
            game.get("short_title"),
            game.get("title"),
            app.get("abbreviated_title"),
            app.get("short_title"),
            app.get("title"),
            ou.get("abbreviated_title"),
            ou.get("title"),
        ))
        game_time = _game_time(game, app, app_stat, ou, line)

        # Rank — lower = more featured; invert for trending_count parity
        raw_rank  = line.get("rank", 999_999_999)

        name = (
            f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            or "Unknown"
        )

        raw_line = line.get("stat_value")
        try:
            normalized_line = float(raw_line) if raw_line is not None else None
        except (TypeError, ValueError):
            normalized_line = None

        results.append({
            "projection_id": line.get("id"),
            "player_id":     player_id,
            "player":        name,
            "team":          str(_first_value(
                player.get("team_id"),
                app.get("team_id"),
                _nested_id(player.get("team")),
                _nested_id(app.get("team")),
            )),
            "league":        league,
            "position":      player.get("position_name", ""),
            "stat":          app_stat.get("display_stat", ""),
            "line":          normalized_line,
            "game":          matchup,
            "game_time":      game_time,
            "match_id":       match_id,
            "season_type":    _season_type(raw_sport, game, app_stat),
            "status":        "pre_game",
            "trending_count": _rank_to_trending(raw_rank),
            "rank":          raw_rank,
            "image_url":     player.get("image_url", ""),
            "platform":      "Underdog",
            "stale":         cached.stale,
            "cache_age_seconds": cached.age_seconds,
        })

    return results


def _rank_to_trending(rank: int) -> int:
    """
    Convert Underdog's ascending rank (lower = more featured) to a
    descending trending_count so it sorts the same way as PrizePicks.

    Observed rank values are in the range ~1e9–1e12, so we scale by 1e13
    to ensure the result is always a positive integer.
    """
    safe = max(rank, 1)
    return int(10_000_000_000_000 / safe)


def top_props(n: int = 25, sport: Optional[str] = None) -> list[dict]:
    """
    Return the top-N Underdog props sorted by featured rank.

    Args:
        n:     Number of props to return.
        sport: Optional sport filter ('NBA', 'WNBA', 'NFL', 'MLB').
    """
    try:
        props = fetch_projections()
    except RuntimeError:
        return []

    if sport:
        props = [p for p in props if p["league"] == sport.upper()]

    # Sort by trending_count descending (derived from rank ascending)
    props.sort(key=lambda p: p["trending_count"], reverse=True)

    return props[:n]
