"""ESPN public injury feed — no API key required."""

from __future__ import annotations

import requests
from typing import Optional

_SPORT_ENDPOINTS = {
    "NBA":  "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
    "WNBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/injuries",
    "NFL":  "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries",
    "MLB":  "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

_STATUS_LABELS = {
    "Out":          "🔴 Out",
    "Doubtful":     "🔴 Doubtful",
    "Questionable": "🟡 Questionable",
    "Day-To-Day":   "🟡 Day-To-Day",
    "Probable":     "🟢 Probable",
}


def fetch_injuries(sport: str) -> list[dict]:
    """
    Fetch current injuries for a sport from ESPN.

    Returns a list of dicts with keys:
        player, team, status, detail, sport
    """
    url = _SPORT_ENDPOINTS.get(sport.upper())
    if not url:
        return []

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = []

    for item in data.get("injuries", []):
        athlete = item.get("athlete", {})
        team    = item.get("team", {})
        status  = item.get("status", "")
        detail  = item.get("shortComment") or item.get("longComment") or ""

        label = _STATUS_LABELS.get(status, f"⚪ {status}")

        results.append({
            "player": athlete.get("displayName", "Unknown"),
            "team":   team.get("abbreviation", ""),
            "status": label,
            "detail": detail,
            "sport":  sport.upper(),
        })

    return results


def fetch_all_injuries() -> list[dict]:
    """Fetch injuries for all supported sports and merge."""
    all_injuries = []
    for sport in _SPORT_ENDPOINTS:
        all_injuries.extend(fetch_injuries(sport))
    return all_injuries


def is_injured(player_name: str, injuries: list[dict]) -> Optional[dict]:
    """
    Return the injury record for a player if found, else None.
    Case-insensitive partial match on player name.
    """
    name_lower = player_name.lower()
    for inj in injuries:
        if name_lower in inj["player"].lower():
            return inj
    return None
