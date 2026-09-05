"""Verified esports final-stat evidence from PandaScore's official API."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from data.providers.cache import get_json
from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.entity_normalization import canonical_matchup_key, canonical_person_key

_BASE = "https://api.pandascore.co"
_SPORT_PATHS = {
    "CS2": "csgo",
    "LOL": "lol",
    "DOTA2": "dota2",
    "VALORANT": "valorant",
}
_STAT_FIELDS = {
    "kills": ("kills", "kill"),
    "deaths": ("deaths", "death"),
    "assists": ("assists", "assist"),
    "headshots": ("headshots", "head_shots", "headshot_kills"),
    "first kills": ("first_kills", "firstkills"),
    "aces": ("aces",),
    "clutches": ("clutches",),
}
_STAT_ALIASES = {
    "eliminations": "kills",
    "headshot kills": "headshots",
    "hs": "headshots",
}


def configured() -> bool:
    return bool(os.getenv("PANDASCORE_API_KEY", "").strip()) and _env_enabled(
        "PANDASCORE_HISTORICAL_STATS_ENABLED"
    )


def key_configured() -> bool:
    return bool(os.getenv("PANDASCORE_API_KEY", "").strip())


def supported_sports() -> tuple[str, ...]:
    return tuple(_SPORT_PATHS)


def market_support(sport: object, stat: object) -> dict[str, Any]:
    sport_key = str(sport or "").strip().upper()
    stat_key = _base_stat(stat)
    reasons: list[str] = []
    if sport_key not in _SPORT_PATHS:
        reasons.append(f"PandaScore final-player-stat coverage is unavailable for {sport_key or 'this sport'}")
    if stat_key not in _STAT_FIELDS and stat_key not in {"kills deaths", "kills assists", "kd"}:
        reasons.append(f"PandaScore cannot verify {str(stat or 'this market')} with a documented player-stat field")
    if "fantasy" in str(stat or "").lower():
        reasons.append("Fantasy score requires the sportsbook's exact scoring formula")
    if not configured():
        reasons.append("PandaScore historical-stat access is not configured")
    return {
        "eligible": not reasons,
        "provider": "PandaScore verified results",
        "reasons": reasons,
        "sport": sport_key,
        "stat": stat_key,
    }


def refresh_final_stats_for_entries(entries: list[dict], lookback_days: int = 2) -> dict[str, Any]:
    esports_entries = [
        entry for entry in entries
        if any(str(prop.get("sport") or "").upper() in _SPORT_PATHS for prop in entry.get("props", []))
    ]
    if not esports_entries:
        return _result(skipped=True, reason="No supported esports entries need final stats.")
    if not configured():
        return _result(
            skipped=True,
            reason="Set PANDASCORE_API_KEY with Historical plan access to verify esports player props.",
        )

    rows: list[dict] = []
    errors: list[str] = []
    matches_checked = 0
    requests_by_sport_date: dict[tuple[str, date], list[dict]] = defaultdict(list)
    for entry in esports_entries:
        for prop in entry.get("props", []):
            sport = str(prop.get("sport") or "").upper()
            if sport not in _SPORT_PATHS:
                continue
            game_date = _prop_date(prop, entry)
            for offset in range(-lookback_days, lookback_days + 1):
                requests_by_sport_date[(sport, game_date + timedelta(days=offset))].append(prop)

    seen_matches: set[tuple[str, str]] = set()
    for (sport, game_date), props in sorted(requests_by_sport_date.items(), key=lambda item: item[0]):
        try:
            matches = _past_matches(sport, game_date)
        except RuntimeError as exc:
            errors.append(f"{sport} {game_date.isoformat()}: {exc}")
            continue
        for match in matches:
            match_id = str(match.get("id") or "")
            if not match_id or (sport, match_id) in seen_matches or not _is_finished(match):
                continue
            matching_props = [prop for prop in props if _prop_matches_match(prop, match, game_date)]
            if not matching_props:
                continue
            seen_matches.add((sport, match_id))
            matches_checked += 1
            try:
                stats = _match_player_stats(sport, match_id)
                rows.extend(_rows_for_match(sport, match, game_date, matching_props, stats))
            except RuntimeError as exc:
                errors.append(f"{sport} match {match_id}: {exc}")

    imported = FinalStatsRepository.upsert_many(rows) if rows else 0
    return _result(
        sports=sorted({sport for sport, _ in requests_by_sport_date}),
        matches_checked=matches_checked,
        fetched_rows=len(rows),
        imported=imported,
        errors=errors,
    )


def _past_matches(sport: str, game_date: date) -> list[dict]:
    start = datetime.combine(game_date, datetime.min.time(), tzinfo=UTC).isoformat().replace("+00:00", "Z")
    end = datetime.combine(game_date, datetime.max.time(), tzinfo=UTC).isoformat().replace("+00:00", "Z")
    query = urlencode({"range[begin_at]": f"{start},{end}", "per_page": 100, "sort": "begin_at"})
    payload = _request(f"/{_SPORT_PATHS[sport]}/matches/past?{query}", ttl_seconds=3600)
    return _list_payload(payload)


def _match_player_stats(sport: str, match_id: str) -> list[dict]:
    payload = _request(f"/{_SPORT_PATHS[sport]}/matches/{match_id}/players/stats", ttl_seconds=86400)
    return _list_payload(payload, keys=("players", "stats", "data"))


def _request(path: str, *, ttl_seconds: int) -> Any:
    token = os.getenv("PANDASCORE_API_KEY", "").strip()
    try:
        response = get_json(
            f"{_BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
            ttl_seconds=ttl_seconds,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"PandaScore refresh failed: {exc}") from exc
    if response.stale:
        raise RuntimeError("PandaScore returned cached data after a failed refresh; it was not used for settlement.")
    return response.data


def _rows_for_match(
    sport: str,
    match: dict,
    game_date: date,
    props: list[dict],
    player_stats: list[dict],
) -> list[dict]:
    matchup = _matchup(match)
    rows: list[dict] = []
    for prop in props:
        player_key = canonical_person_key(prop.get("player"))
        candidates = [row for row in player_stats if canonical_person_key(_player_name(row)) == player_key]
        if len(candidates) != 1:
            continue
        actual = _actual_for_market(candidates[0], prop.get("stat"))
        if actual is None:
            continue
        player = _player_name(candidates[0])
        rows.append({
            "player": player,
            "team": _team_name(candidates[0]) or str(prop.get("team") or ""),
            "sport": sport,
            "stat": str(prop.get("stat") or ""),
            "game": matchup,
            "game_date": game_date.isoformat(),
            "actual": actual,
            "status": "played",
            "source": "pandascore_verified",
            "player_provider": "PandaScore",
            "provider_player_id": _player_id(candidates[0]),
        })
    return rows


def _actual_for_market(row: dict, stat: object) -> float | None:
    stat_key = _base_stat(stat)
    maps = _requested_maps(stat)
    game_rows = _game_rows(row)
    if maps:
        selected = []
        for map_number in maps:
            game = next((item for item in game_rows if _game_number(item) == map_number), None)
            if game is None:
                return None
            selected.append(game)
        return _sum_stat(selected, stat_key)
    return _sum_stat([row], stat_key)


def _sum_stat(rows: list[dict], stat_key: str) -> float | None:
    component_keys = {
        "kills deaths": ("kills", "deaths"),
        "kd": ("kills", "deaths"),
        "kills assists": ("kills", "assists"),
    }.get(stat_key, (stat_key,))
    total = 0.0
    for row in rows:
        for component in component_keys:
            value = _numeric_field(row, _STAT_FIELDS.get(component, (component,)))
            if value is None:
                return None
            total += value
    return total


def _numeric_field(row: dict, fields: tuple[str, ...]) -> float | None:
    containers = [row, row.get("stats") or {}, row.get("totals") or {}]
    for container in containers:
        for field in fields:
            value = container.get(field) if isinstance(container, dict) else None
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                continue
    return None


def _requested_maps(stat: object) -> tuple[int, ...]:
    text = str(stat or "").lower()
    match = re.search(r"maps?\s*(\d+)\s*(?:\+|&|and|-)\s*(\d+)", text)
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        return tuple(range(first, second + 1)) if "-" in match.group(0) else (first, second)
    match = re.search(r"map\s*(\d+)", text)
    return (int(match.group(1)),) if match else ()


def _base_stat(stat: object) -> str:
    text = re.sub(r"\bmaps?\s*\d+(?:\s*(?:\+|&|and|-)\s*\d+)?\b", "", str(stat or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return _STAT_ALIASES.get(text, text)


def _game_rows(row: dict) -> list[dict]:
    for key in ("games", "maps", "segments"):
        value = row.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    stats = row.get("stats")
    if isinstance(stats, dict):
        for key in ("games", "maps", "segments"):
            value = stats.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _game_number(row: dict) -> int:
    for key in ("map_number", "game_number", "position", "number"):
        try:
            return int(row.get(key))
        except (TypeError, ValueError):
            pass
    return 0


def _player_name(row: dict) -> str:
    player = row.get("player") if isinstance(row.get("player"), dict) else {}
    return str(player.get("name") or player.get("slug") or row.get("player_name") or row.get("name") or "").strip()


def _player_id(row: dict) -> str:
    player = row.get("player") if isinstance(row.get("player"), dict) else {}
    return str(player.get("id") or row.get("player_id") or "").strip()


def _team_name(row: dict) -> str:
    team = row.get("team") if isinstance(row.get("team"), dict) else {}
    return str(team.get("acronym") or team.get("name") or row.get("team_name") or "").strip()


def _matchup(match: dict) -> str:
    opponents = [
        str((item.get("opponent") or {}).get("name") or (item.get("opponent") or {}).get("acronym") or "").strip()
        for item in match.get("opponents", [])
        if isinstance(item, dict)
    ]
    opponents = [name for name in opponents if name]
    return " vs ".join(opponents[:2]) or str(match.get("name") or "").strip()


def _prop_matches_match(prop: dict, match: dict, requested_date: date) -> bool:
    matchup = _matchup(match)
    if not matchup:
        return False
    wanted = canonical_matchup_key(prop.get("game"))
    found = canonical_matchup_key(matchup)
    team = re.sub(r"[^a-z0-9]", "", str(prop.get("team") or "").lower())
    if wanted and wanted != found and not (team and team in found):
        return False
    begin_at = str(match.get("begin_at") or match.get("scheduled_at") or "")
    try:
        match_date = datetime.fromisoformat(begin_at.replace("Z", "+00:00")).date()
    except ValueError:
        match_date = requested_date
    return abs((match_date - requested_date).days) <= 1


def _prop_date(prop: dict, entry: dict) -> date:
    for value in (prop.get("game_time"), entry.get("placed_at")):
        if isinstance(value, datetime):
            return value.date()
        try:
            return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return datetime.now(UTC).date()


def _is_finished(match: dict) -> bool:
    return str(match.get("status") or "").lower() in {"finished", "completed"}


def _list_payload(payload: Any, keys: tuple[str, ...] = ("data",)) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _result(**values: Any) -> dict[str, Any]:
    return {
        "provider": "pandascore",
        "sports": [],
        "matches_checked": 0,
        "fetched_rows": 0,
        "imported": 0,
        "errors": [],
        **values,
    }


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
