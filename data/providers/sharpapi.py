"""Optional SharpAPI player-prop fallback, with explicit third-party provenance."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from urllib.parse import urlencode

from data.providers.cache import get_json
from utils.sports import SUPPORTED_SPORTS
from utils.stat_normalization import canonical_stat_label

_BASE = "https://api.sharpapi.io/api/v1/odds"
_LEAGUES = ("nba", "wnba", "nfl", "ncaaf", "mlb", "nhl")
_STATS = {
    "points", "rebounds", "assists", "steals", "blocks", "turnovers",
    "3 pointers made", "field goals made", "field goals attempted",
    "passing yards", "passing attempts", "passing tds", "rushing yards",
    "rushing attempts", "receiving yards", "receptions", "targets",
    "hits", "runs", "rbis", "home runs", "total bases", "strikeouts",
    "pitcher strikeouts", "goals", "shots on goal", "saves",
}


def normalize_player_prop(row: dict, *, stale: bool = False) -> dict | None:
    if not isinstance(row, dict) or row.get("is_live") or row.get("is_active") is False:
        return None
    if row.get("is_stale_pregame_price") or row.get("is_main_line") is not True:
        return None
    if row.get("market_segment") not in (None, "", "full_game"):
        return None
    market = str(row.get("market_type") or "")
    if not market.startswith("player_"):
        return None
    stat = canonical_stat_label(market.removeprefix("player_").replace("_", " "))
    if str(stat).lower() not in _STATS:
        return None
    league = str(row.get("league") or "").upper()
    player = str(row.get("player_name") or "").strip()
    side = str(row.get("selection_type") or "").lower()
    start = str(row.get("event_start_time") or "")
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        line = float(row["line"])
    except (ValueError, TypeError, KeyError):
        return None
    if (league not in SUPPORTED_SPORTS or not player or side not in {"over", "under"}
            or start_dt.tzinfo is None or start_dt <= datetime.now(UTC)):
        return None
    home = str(row.get("home_team") or "").strip()
    away = str(row.get("away_team") or "").strip()
    if not home or not away or not row.get("event_id") or not row.get("id"):
        return None
    book = str(row.get("sportsbook") or "").lower()
    platform = {"underdog": "Underdog", "prizepicks": "PrizePicks"}.get(book)
    if platform is None:
        return None
    return {
        "projection_id": f"sharpapi:{row['id']}",
        "provider_offer_id": str(row["id"]),
        "provider_event_id": str(row["event_id"]),
        "player": player,
        "team": "",
        "league": league,
        "stat": stat,
        "line": line,
        "direction": side.title(),
        "game": f"{away} @ {home}",
        "game_time": start,
        "status": "pre_game",
        "platform": platform,
        "line_offer_type": "standard",
        "standard_line": line,
        "is_discounted_line": False,
        "is_premium_line": False,
        "provider_source": "SharpAPI (third-party)",
        "provider_offer_verified_at": "" if stale else str(row.get("timestamp") or ""),
        "stale": stale,
        "payout_evidence": "unverified",
        "odds_american_context": row.get("odds_american"),
    }


def fetch_player_props(sportsbook: str = "underdog", *, max_pages: int = 5) -> list[dict]:
    """Read a bounded snapshot. No API key means this fallback is disabled."""
    key = os.getenv("SHARPAPI_API_KEY", "").strip()
    if not key or sportsbook not in {"underdog", "prizepicks"}:
        return []
    rows: list[dict] = []
    cursor = ""
    seen: set[str] = set()
    for _ in range(max_pages):
        query = {
            "sportsbook": sportsbook,
            "league": ",".join(_LEAGUES),
            "market": "props",
            "is_live": "false",
            "is_main_line": "true",
            "limit": "200",
        }
        if cursor:
            query["cursor"] = cursor
        url = f"{_BASE}?{urlencode(query)}"
        result = get_json(
            url, headers={"X-API-Key": key}, timeout=8, retries=0,
            ttl_seconds=120, cache_key=f"sharpapi:{url}",
        )
        payload = result.data if isinstance(result.data, dict) else {}
        for raw in payload.get("data", []):
            prop = normalize_player_prop(raw, stale=result.stale)
            if prop and prop["projection_id"] not in seen:
                seen.add(prop["projection_id"])
                rows.append(prop)
        page = payload.get("pagination") or {}
        next_cursor = str(page.get("next_cursor") or "")
        if not page.get("has_more") or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return rows
