"""Sleeper provider.

Sleeper's documented public API exposes fantasy players and trending add/drop
activity, not a player-prop line feed. Prop lines can still be configured with
EDGEIQ_SLEEPER_PROPS_URL or EDGEIQ_SLEEPER_PROPS_FILE.
"""

from __future__ import annotations

from typing import Optional

from data.providers.cache import get_json
from data.providers.generic_props import fetch_configured_props


_BASE = "https://api.sleeper.app/v1"
_SPORT_MAP = {
    "NFL": "nfl",
}
_HEADERS = {
    "User-Agent": "EdgeIQ/2.0",
    "Accept": "application/json",
}


def fetch_projections() -> list[dict]:
    return fetch_configured_props("Sleeper", "SLEEPER")


def fetch_trending_players(
    sport: str = "NFL",
    trend_type: str = "add",
    lookback_hours: int = 24,
    limit: int = 50,
) -> list[dict]:
    """Fetch Sleeper add/drop trend rows enriched with player metadata."""
    sport_id = _SPORT_MAP.get(sport.upper())
    if sport_id is None:
        return []
    trend = "drop" if trend_type.lower() == "drop" else "add"
    url = (
        f"{_BASE}/players/{sport_id}/trending/{trend}"
        f"?lookback_hours={lookback_hours}&limit={limit}"
    )
    try:
        rows = get_json(url, headers=_HEADERS, timeout=12, ttl_seconds=300).data
    except RuntimeError:
        return []
    players = fetch_players(sport)
    return [
        {
            "player_id": str(row.get("player_id", "")),
            "count": int(row.get("count") or 0),
            "trend_type": trend,
            **_player_metadata(players.get(str(row.get("player_id", "")), {})),
        }
        for row in rows
        if row.get("player_id")
    ]


def fetch_players(sport: str = "NFL") -> dict[str, dict]:
    sport_id = _SPORT_MAP.get(sport.upper())
    if sport_id is None:
        return {}
    try:
        data = get_json(
            f"{_BASE}/players/{sport_id}",
            headers=_HEADERS,
            timeout=20,
            ttl_seconds=86400,
        ).data
    except RuntimeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(player_id): row for player_id, row in data.items() if isinstance(row, dict)}


def player_trend_signal(player_name: str, sport: str = "NFL") -> dict | None:
    if sport.upper() != "NFL":
        return None
    adds = _find_player_trend(player_name, fetch_trending_players(sport, "add"))
    drops = _find_player_trend(player_name, fetch_trending_players(sport, "drop"))
    if adds is None and drops is None:
        return None
    add_count = adds.get("count", 0) if adds else 0
    drop_count = drops.get("count", 0) if drops else 0
    net = add_count - drop_count
    return {
        "player": player_name,
        "add_count": add_count,
        "drop_count": drop_count,
        "net_adds": net,
        "source": "sleeper",
    }


def top_props(n: int = 25, sport: Optional[str] = None) -> list[dict]:
    props = fetch_projections()
    if sport:
        props = [prop for prop in props if prop.get("league", "").upper() == sport.upper()]
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return props[:n]


def _find_player_trend(player_name: str, trends: list[dict]) -> dict | None:
    needle = player_name.strip().lower()
    for trend in trends:
        name = trend.get("player", "").strip().lower()
        if name == needle or (needle and needle in name):
            return trend
    return None


def _player_metadata(row: dict) -> dict:
    first = row.get("first_name", "")
    last = row.get("last_name", "")
    full_name = row.get("full_name") or f"{first} {last}".strip()
    return {
        "player": full_name,
        "team": row.get("team") or "",
        "position": row.get("position") or "",
        "league": "NFL",
    }
