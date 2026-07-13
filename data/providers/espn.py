"""ESPN public box-score provider for final player stats."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from data.providers.cache import get_json
from repository.repositories.final_stats_repository import FinalStatsRepository


_BASE = "https://site.api.espn.com/apis/site/v2/sports"
_SPORT_PATHS = {
    "WNBA": "basketball/wnba",
    "NBA": "basketball/nba",
    "MLB": "baseball/mlb",
    "NFL": "football/nfl",
}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def refresh_final_stats_for_entries(entries: list[dict], lookback_days: int = 2) -> dict:
    """Fetch ESPN final box scores for the sports/dates represented by entries."""
    sports = sorted({
        str(prop.get("sport", "")).upper()
        for entry in entries
        for prop in entry.get("props", [])
        if str(prop.get("sport", "")).upper() in _SPORT_PATHS
    })
    dates = sorted({_entry_date(entry) for entry in entries})

    rows: list[dict] = []
    errors: list[str] = []
    for sport in sports:
        for game_date in _date_window(dates, lookback_days):
            try:
                rows.extend(fetch_final_stats(sport, game_date))
            except RuntimeError as exc:
                errors.append(f"{sport} {game_date.isoformat()}: {exc}")

    imported = FinalStatsRepository.upsert_many(rows) if rows else 0
    return {
        "provider": "espn",
        "sports": sports,
        "dates": [day.isoformat() for day in _date_window(dates, lookback_days)],
        "fetched_rows": len(rows),
        "imported": imported,
        "errors": errors,
    }


def fetch_final_stats(sport: str, game_date: date) -> list[dict]:
    sport_key = sport.upper()
    path = _SPORT_PATHS.get(sport_key)
    if path is None:
        return []

    scoreboard = _scoreboard(path, game_date)
    rows: list[dict] = []
    for event in scoreboard.get("events", []):
        competition = _first(event.get("competitions", []))
        status = (competition.get("status", {}) if competition else {}).get("type", {})
        if not status.get("completed"):
            continue
        event_id = event.get("id")
        if not event_id:
            continue
        summary = _summary(path, event_id)
        rows.extend(_parse_summary(summary, sport_key, game_date))
    return rows


def _scoreboard(path: str, game_date: date) -> dict:
    dates = game_date.strftime("%Y%m%d")
    url = f"{_BASE}/{path}/scoreboard?dates={dates}"
    return get_json(url, headers=_HEADERS, timeout=12, ttl_seconds=900).data


def _summary(path: str, event_id: str) -> dict:
    url = f"{_BASE}/{path}/summary?event={event_id}"
    return get_json(url, headers=_HEADERS, timeout=12, ttl_seconds=86400).data


def _parse_summary(summary: dict, sport: str, game_date: date) -> list[dict]:
    if sport in {"WNBA", "NBA"}:
        return _parse_basketball_summary(summary, sport, game_date)
    return []


def _parse_basketball_summary(summary: dict, sport: str, game_date: date) -> list[dict]:
    rows: list[dict] = []
    matchup = _matchup(summary)
    for team_group in summary.get("boxscore", {}).get("players", []):
        team = team_group.get("team", {})
        team_abbr = team.get("abbreviation", "")
        for stat_group in team_group.get("statistics", []):
            labels = stat_group.get("names") or stat_group.get("labels") or []
            for athlete_row in stat_group.get("athletes", []):
                athlete = athlete_row.get("athlete", {})
                player = athlete.get("displayName", "")
                if not player:
                    continue
                if athlete_row.get("didNotPlay"):
                    rows.extend(_dnp_rows(player, team_abbr, sport, matchup, game_date))
                    continue
                stats = _stats_by_label(labels, athlete_row.get("stats", []))
                rows.extend(_basketball_stat_rows(player, team_abbr, sport, matchup, game_date, stats))
    return rows


def _basketball_stat_rows(
    player: str,
    team: str,
    sport: str,
    game: str,
    game_date: date,
    stats: dict[str, float],
) -> list[dict]:
    points = stats.get("PTS", 0.0)
    rebounds = stats.get("REB", 0.0)
    assists = stats.get("AST", 0.0)
    steals = stats.get("STL", 0.0)
    blocks = stats.get("BLK", 0.0)
    turnovers = stats.get("TO", 0.0)

    values = {
        "Points": points,
        "Rebounds": rebounds,
        "Assists": assists,
        "Steals": steals,
        "Blocks": blocks,
        "Turnovers": turnovers,
        "PRA": points + rebounds + assists,
        "Points + Rebounds + Assists": points + rebounds + assists,
        "Points+Rebounds+Assists": points + rebounds + assists,
        "Points + Rebounds": points + rebounds,
        "Points+Rebounds": points + rebounds,
        "Points + Assists": points + assists,
        "Points+Assists": points + assists,
        "Rebounds + Assists": rebounds + assists,
        "Rebounds+Assists": rebounds + assists,
        "Steals + Blocks": steals + blocks,
        "Steals+Blocks": steals + blocks,
    }
    return [
        _row(player, team, sport, stat, game, game_date, actual, "played")
        for stat, actual in values.items()
    ]


def _dnp_rows(player: str, team: str, sport: str, game: str, game_date: date) -> list[dict]:
    stats = [
        "Points",
        "Rebounds",
        "Assists",
        "Steals",
        "Blocks",
        "Turnovers",
        "PRA",
        "Points + Rebounds + Assists",
        "Points+Rebounds+Assists",
        "Points + Rebounds",
        "Points+Rebounds",
        "Points + Assists",
        "Points+Assists",
        "Rebounds + Assists",
        "Rebounds+Assists",
        "Steals + Blocks",
        "Steals+Blocks",
    ]
    return [_row(player, team, sport, stat, game, game_date, 0.0, "dnp") for stat in stats]


def _row(
    player: str,
    team: str,
    sport: str,
    stat: str,
    game: str,
    game_date: date,
    actual: float,
    status: str,
) -> dict:
    return {
        "player": player,
        "team": team,
        "sport": sport,
        "stat": stat,
        "game": game,
        "game_date": game_date.isoformat(),
        "actual": round(float(actual), 2),
        "status": status,
        "source": "espn",
    }


def _stats_by_label(labels: Iterable[str], values: Iterable[Any]) -> dict[str, float]:
    stats: dict[str, float] = {}
    for label, value in zip(labels, values, strict=False):
        stats[str(label).upper()] = _numeric(value)
    return stats


def _numeric(value: Any) -> float:
    text = str(value or "0").strip()
    if not text:
        return 0.0
    if "-" in text and not text.startswith("-"):
        return 0.0
    try:
        return float(text.replace("+", ""))
    except ValueError:
        return 0.0


def _matchup(summary: dict) -> str:
    competitors = (
        summary.get("header", {})
        .get("competitions", [{}])[0]
        .get("competitors", [])
    )
    away = home = ""
    for competitor in competitors:
        abbr = competitor.get("team", {}).get("abbreviation", "")
        if competitor.get("homeAway") == "away":
            away = abbr
        elif competitor.get("homeAway") == "home":
            home = abbr
    return f"{away}@{home}".strip("@") if away or home else ""


def _entry_date(entry: dict) -> date:
    placed_at = entry.get("placed_at")
    if isinstance(placed_at, datetime):
        return placed_at.date()
    if isinstance(placed_at, str) and placed_at:
        try:
            return datetime.fromisoformat(placed_at).date()
        except ValueError:
            pass
    return date.today()


def _date_window(dates: list[date], lookback_days: int) -> list[date]:
    if not dates:
        dates = [date.today()]
    window = set(dates)
    for day in dates:
        for offset in range(1, lookback_days + 1):
            window.add(day - timedelta(days=offset))
            window.add(day + timedelta(days=offset))
    return sorted(window)


def _first(items: list[dict]) -> dict:
    return items[0] if items else {}
