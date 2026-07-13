"""Optional SportsDataIO final-stat provider.

Set SPORTSDATAIO_API_KEY to enable. ESPN remains the no-key default provider;
this module is a paid-data upgrade path and returns no rows when unconfigured.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from data.providers.cache import get_json


_BASES = {
    "NBA": "https://api.sportsdata.io/v3/nba/stats/json",
    "NFL": "https://api.sportsdata.io/v3/nfl/stats/json",
    "MLB": "https://api.sportsdata.io/v3/mlb/stats/json",
}


def fetch_final_stats(sport: str, game_date: date) -> list[dict]:
    api_key = os.getenv("SPORTSDATAIO_API_KEY", "").strip()
    sport_key = sport.upper()
    base = _BASES.get(sport_key)
    if not api_key or base is None:
        return []

    url = _stats_url(base, sport_key, game_date, api_key)
    data = get_json(url, timeout=20, ttl_seconds=86400).data
    rows = data if isinstance(data, list) else data.get("PlayerGames", []) if isinstance(data, dict) else []
    return [_row for raw in rows for _row in _normalize_rows(raw, sport_key, game_date)]


def _stats_url(base: str, sport: str, game_date: date, api_key: str) -> str:
    date_token = game_date.strftime("%Y-%b-%d").upper()
    if sport == "MLB":
        endpoint = f"PlayerGameStatsByDate/{date_token}"
    else:
        endpoint = f"PlayerGameStatsByDate/{date_token}"
    return f"{base}/{endpoint}?key={api_key}"


def _normalize_rows(raw: dict[str, Any], sport: str, game_date: date) -> list[dict]:
    player = _value(raw, "Name", "PlayerName", "Player")
    team = _value(raw, "Team", "TeamID")
    if not player:
        return []

    if sport == "MLB":
        values = _mlb_values(raw)
    elif sport == "NFL":
        values = _nfl_values(raw)
    else:
        values = _basketball_values(raw)

    game = _value(raw, "Opponent", "HomeOrAway", "GameKey")
    return [
        {
            "player": player,
            "team": team,
            "sport": sport,
            "stat": stat,
            "game": game,
            "game_date": game_date.isoformat(),
            "actual": round(float(actual), 2),
            "status": "played",
            "source": "sportsdataio",
        }
        for stat, actual in values.items()
    ]


def _basketball_values(raw: dict[str, Any]) -> dict[str, float]:
    points = _num(raw, "Points")
    rebounds = _num(raw, "Rebounds")
    assists = _num(raw, "Assists")
    steals = _num(raw, "Steals")
    blocks = _num(raw, "BlockedShots", "Blocks")
    turnovers = _num(raw, "Turnovers")
    threes = _num(raw, "ThreePointersMade")
    return {
        "Points": points,
        "Rebounds": rebounds,
        "Assists": assists,
        "3-Pointers Made": threes,
        "Blocks": blocks,
        "Steals": steals,
        "Turnovers": turnovers,
        "PRA": points + rebounds + assists,
        "Points + Rebounds + Assists": points + rebounds + assists,
        "Points + Rebounds": points + rebounds,
        "Points + Assists": points + assists,
        "Rebounds + Assists": rebounds + assists,
        "Steals + Blocks": steals + blocks,
    }


def _mlb_values(raw: dict[str, Any]) -> dict[str, float]:
    hits = _num(raw, "Hits")
    runs = _num(raw, "Runs")
    rbis = _num(raw, "RunsBattedIn", "RBIs")
    total_bases = _num(raw, "TotalBases")
    strikeouts = _num(raw, "Strikeouts")
    pitcher_strikeouts = _num(raw, "PitchingStrikeouts")
    return {
        "Hits": hits,
        "Runs": runs,
        "RBIs": rbis,
        "Hits+Runs+RBIs": hits + runs + rbis,
        "Total Bases": total_bases,
        "Ks": pitcher_strikeouts or strikeouts,
    }


def _nfl_values(raw: dict[str, Any]) -> dict[str, float]:
    passing = _num(raw, "PassingYards")
    rushing = _num(raw, "RushingYards")
    receiving = _num(raw, "ReceivingYards")
    receptions = _num(raw, "Receptions")
    touchdowns = (
        _num(raw, "PassingTouchdowns")
        + _num(raw, "RushingTouchdowns")
        + _num(raw, "ReceivingTouchdowns")
    )
    return {
        "Passing Yards": passing,
        "Rushing Yards": rushing,
        "Receiving Yards": receiving,
        "Receptions": receptions,
        "Touchdowns": touchdowns,
        "Rush+Rec Yards": rushing + receiving,
    }


def _value(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _num(raw: dict[str, Any], *keys: str) -> float:
    value = _value(raw, *keys)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
