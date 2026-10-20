"""Verified match-level tennis results from Sportradar Tennis v3."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from data.providers.cache import get_json
from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.entity_normalization import canonical_matchup_key, canonical_person_key

MARKETS = {"aces": "Aces", "double_faults": "Double Faults", "games_won": "Games Won"}
_ALIASES = {"aces": "aces", "double faults": "double_faults", "games won": "games_won"}
_ET = ZoneInfo("America/New_York")


def configured() -> bool:
    return bool(os.getenv("SPORTRADAR_TENNIS_API_KEY", "").strip())


def supported_market(stat: object) -> bool:
    return str(stat or "").strip().lower() in _ALIASES


def fetch_daily_summaries(day: date) -> list[dict]:
    key = os.getenv("SPORTRADAR_TENNIS_API_KEY", "").strip()
    if not key:
        return []
    level = os.getenv("SPORTRADAR_TENNIS_ACCESS_LEVEL", "trial").strip().lower()
    if level not in {"trial", "production"}:
        raise RuntimeError("Invalid Sportradar Tennis access level")
    url = f"https://api.sportradar.com/tennis/{level}/v3/en/schedules/{day.isoformat()}/summaries.json"
    response = get_json(
        url, cache_key=f"sportradar-tennis-{level}-{day.isoformat()}",
        headers={"x-api-key": key, "Accept": "application/json"},
        ttl_seconds=300, timeout=12, retries=0,
    )
    if response.stale:
        raise RuntimeError("Tennis results are stale; settlement will retry")
    return response.data.get("summaries", []) if isinstance(response.data, dict) else []


def _player_name(name: object) -> str:
    value = str(name or "").strip()
    if "," in value:
        surname, given = value.split(",", 1)
        return f"{given.strip()} {surname.strip()}".strip()
    return value


def match_competitors(summary: dict) -> list[str]:
    event = summary.get("sport_event") or {}
    competitors = event.get("competitors") or []
    if len(competitors) != 2:
        return []
    return [_player_name(row.get("name")) for row in competitors]


def offer_support(prop: dict) -> tuple[bool, str]:
    """Require an exact singles matchup and match-specific stat coverage."""
    if not configured():
        return False, "Tennis results feed is not configured"
    stat = str(prop.get("stat") or "").strip().lower()
    if stat not in _ALIASES:
        return False, "Tennis market is not supported by the results feed"
    try:
        start = datetime.fromisoformat(str(prop.get("game_time") or "").replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        candidate_days = {start.astimezone(_ET).date(), start.astimezone(UTC).date()}
    except ValueError:
        return False, "Tennis match start time is missing"
    player_key = canonical_person_key(prop.get("player"))
    matchup_key = canonical_matchup_key(prop.get("game"))
    if not player_key or "@" not in matchup_key:
        return False, "Full tennis matchup is required for result matching"
    try:
        summaries = [summary for day in sorted(candidate_days) for summary in fetch_daily_summaries(day)]
    except RuntimeError:
        return False, "Tennis match coverage could not be verified right now"
    matches = []
    for summary in summaries:
        names = match_competitors(summary)
        if len(names) != 2 or player_key not in {canonical_person_key(name) for name in names}:
            continue
        if canonical_matchup_key(f"{names[0]} vs {names[1]}") != matchup_key:
            continue
        try:
            event_start = datetime.fromisoformat(
                str(summary["sport_event"]["start_time"]).replace("Z", "+00:00")
            )
            if event_start.tzinfo is None or abs((event_start - start).total_seconds()) > 18 * 3600:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        matches.append(summary)
    unique_matches = {str(row["sport_event"].get("id")): row for row in matches}
    if len(unique_matches) != 1 or "" in unique_matches:
        return False, "Tennis match could not be matched uniquely to the results feed"
    event = next(iter(unique_matches.values()))["sport_event"]
    coverage = (event.get("coverage") or {}).get("sport_event_properties") or {}
    if stat in {"aces", "double faults"} and coverage.get("detailed_serve_outcomes") is not True:
        return False, "This match does not have verified serve-stat coverage"
    if stat == "games won" and coverage.get("scores") not in {"live", "post"}:
        return False, "This match does not have verified scoring coverage"
    return True, "Sportradar Tennis v3 match and market coverage verified"


def parse_final_rows(summary: dict) -> list[dict]:
    event = summary.get("sport_event") or {}
    status = summary.get("sport_event_status") or {}
    if status.get("status") not in {"ended", "closed"} or status.get("winning_reason"):
        return []
    competitors = event.get("competitors") or []
    if len(competitors) != 2 or any(row.get("players") for row in competitors):
        return []
    by_id = {str(row.get("id")): row for row in competitors if row.get("id")}
    if len(by_id) != 2:
        return []
    start = str(event.get("start_time") or "")
    try:
        game_date = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(_ET).date().isoformat()
    except ValueError:
        return []
    names = [_player_name(row.get("name")) for row in competitors]
    if not all(names) or len({canonical_person_key(name) for name in names}) != 2:
        return []
    game = f"{names[0]} vs {names[1]}"
    rows = []
    totals = ((summary.get("statistics") or {}).get("totals") or {}).get("competitors") or []
    for result in totals:
        competitor = by_id.get(str(result.get("id")))
        if not competitor:
            continue
        stats = result.get("statistics") or {}
        for field, label in MARKETS.items():
            value = stats.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                continue
            rows.append({
                "player": _player_name(competitor.get("name")), "sport": "TENNIS",
                "stat": label, "actual": value, "game": game, "game_date": game_date,
                "status": "played", "source": "sportradar_tennis_v3",
                "player_provider": "sportradar", "provider_player_id": str(competitor["id"]),
            })
    return rows


def refresh_final_stats_for_entries(entries: list[dict]) -> dict:
    props = [prop for entry in entries for prop in entry.get("props", [])
             if str(prop.get("sport") or "").upper() == "TENNIS"]
    if not props or not configured():
        return {"provider": "sportradar_tennis_v3", "skipped": True, "imported": 0, "fetched_rows": 0, "errors": []}
    days = set()
    for prop in props:
        try:
            start = datetime.fromisoformat(str(prop.get("game_time") or "").replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            days.update((start.astimezone(_ET).date(), start.astimezone(UTC).date()))
        except ValueError:
            continue
    rows = []
    errors = []
    # A postponed match can move to the following date without changing its offer id.
    for day in sorted(days | {day + timedelta(days=1) for day in days}):
        try:
            for summary in fetch_daily_summaries(day):
                rows.extend(parse_final_rows(summary))
        except RuntimeError as exc:
            errors.append(f"{day.isoformat()}: {exc}")
    imported = FinalStatsRepository.upsert_many(rows) if rows else 0
    return {"provider": "sportradar_tennis_v3", "imported": imported, "fetched_rows": len(rows), "errors": errors}
