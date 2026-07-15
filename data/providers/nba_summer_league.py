"""NBA Stats fallback for Summer League player box scores.

The public NBA Stats endpoints expose Summer League games through
LeagueGameFinder. We use that to discover game IDs, then fetch traditional box
scores and normalize them into EdgeIQ's final-player-stat shape.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from data.providers.cache import get_json
from repository.repositories.final_stats_repository import FinalStatsRepository


_BASE = "https://stats.nba.com/stats"
_HEADERS = {
    "Host": "stats.nba.com",
    "Connection": "keep-alive",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}
_SEASON_TYPE = "Summer League"


def refresh_final_stats_for_entries(entries: list[dict], lookback_days: int = 3) -> dict:
    nba_entries = [
        entry for entry in entries
        if any(str(prop.get("sport", "")).upper() == "NBA" for prop in entry.get("props", []))
    ]
    if not nba_entries:
        return _empty(skipped=True)

    window = _date_window([_entry_date(entry) for entry in nba_entries], lookback_days)
    rows: list[dict] = []
    fetched_games = 0
    errors: list[str] = []
    seen_game_ids: set[str] = set()

    try:
        games = fetch_summer_league_games_between(window[0], window[-1])
    except RuntimeError as exc:
        errors.append(f"{window[0].isoformat()} to {window[-1].isoformat()}: {exc}")
        games = []

    for game in games:
        game_id = str(game.get("GAME_ID") or "").strip()
        if not game_id or game_id in seen_game_ids:
            continue
        seen_game_ids.add(game_id)
        try:
            game_rows = fetch_box_score(game_id, game)
        except RuntimeError as exc:
            errors.append(f"{game_id}: {exc}")
            continue
        fetched_games += 1
        rows.extend(game_rows)

    imported = FinalStatsRepository.upsert_many(rows) if rows else 0
    return {
        "provider": "nba_summer_league",
        "sports": ["NBA"],
        "season_type": _SEASON_TYPE,
        "dates": [day.isoformat() for day in window],
        "games": fetched_games,
        "fetched_rows": len(rows),
        "imported": imported,
        "errors": errors,
    }


def fetch_summer_league_games(game_date: date) -> list[dict]:
    return fetch_summer_league_games_between(game_date, game_date)


def fetch_summer_league_games_between(date_from: date, date_to: date) -> list[dict]:
    payload = _get_json("leaguegamefinder", _league_game_finder_params(date_from, date_to), ttl_seconds=3600)
    rows = _result_rows(payload, "LeagueGameFinderResults")
    unique: dict[str, dict] = {}
    for row in rows:
        game_id = str(row.get("GAME_ID") or "").strip()
        if not game_id:
            continue
        existing = unique.setdefault(game_id, row)
        if "MATCHUP" not in existing and row.get("MATCHUP"):
            existing["MATCHUP"] = row["MATCHUP"]
    return list(unique.values())


def fetch_box_score(game_id: str, game: dict | None = None) -> list[dict]:
    payload = _get_json("boxscoretraditionalv2", _box_score_params(game_id), ttl_seconds=86400)
    game = game or {}
    game_date = _parse_game_date(game.get("GAME_DATE")) or date.today()
    matchup = _normalize_matchup(game.get("MATCHUP", ""))
    return [
        row
        for raw in _result_rows(payload, "PlayerStats")
        for row in _player_stat_rows(raw, matchup, game_date)
    ]


def _league_game_finder_params(date_from: date, date_to: date | None = None) -> dict[str, str]:
    from_token = date_from.strftime("%m/%d/%Y")
    to_token = (date_to or date_from).strftime("%m/%d/%Y")
    return {
        "Conference": "",
        "DateFrom": from_token,
        "DateTo": to_token,
        "Division": "",
        "DraftNumber": "",
        "DraftRound": "",
        "DraftTeamID": "",
        "DraftYear": "",
        "GameID": "",
        "LeagueID": "00",
        "Location": "",
        "Outcome": "",
        "PORound": "",
        "PlayerID": "",
        "PlayerOrTeam": "T",
        "RookieYear": "",
        "Season": "",
        "SeasonSegment": "",
        "SeasonType": _SEASON_TYPE,
        "StarterBench": "",
        "TeamID": "",
        "VsConference": "",
        "VsDivision": "",
        "VsTeamID": "",
        "YearsExperience": "",
    }


def _box_score_params(game_id: str) -> dict[str, str | int]:
    return {
        "EndPeriod": 10,
        "EndRange": 0,
        "GameID": game_id,
        "RangeType": 0,
        "StartPeriod": 1,
        "StartRange": 0,
    }


def _get_json(endpoint: str, params: dict[str, object], ttl_seconds: int) -> dict:
    url = f"{_BASE}/{endpoint}?{urlencode(params)}"
    data = get_json(url, headers=_HEADERS, timeout=8, ttl_seconds=ttl_seconds, retries=0).data
    return data if isinstance(data, dict) else {}


def _result_rows(payload: dict, preferred_name: str) -> list[dict]:
    result_sets = payload.get("resultSets") or payload.get("result_sets") or []
    for result_set in result_sets:
        name = result_set.get("name") or result_set.get("Name")
        if name != preferred_name:
            continue
        headers = result_set.get("headers") or result_set.get("Headers") or []
        rows = result_set.get("rowSet") or result_set.get("RowSet") or []
        return [dict(zip(headers, row, strict=False)) for row in rows]
    return []


def _player_stat_rows(raw: dict[str, Any], game: str, game_date: date) -> list[dict]:
    player = str(raw.get("PLAYER_NAME") or "").strip()
    team = str(raw.get("TEAM_ABBREVIATION") or "").strip()
    if not player:
        return []

    values = _basketball_values(raw)
    status = "dnp" if _is_dnp(raw) else "played"
    return [
        {
            "player": player,
            "team": team,
            "sport": "NBA",
            "stat": stat,
            "game": game,
            "game_date": game_date.isoformat(),
            "actual": round(float(actual), 2),
            "status": status,
            "source": "nba_summer_league",
        }
        for stat, actual in values.items()
    ]


def _basketball_values(raw: dict[str, Any]) -> dict[str, float]:
    points = _num(raw, "PTS")
    rebounds = _num(raw, "REB")
    assists = _num(raw, "AST")
    steals = _num(raw, "STL")
    blocks = _num(raw, "BLK")
    turnovers = _num(raw, "TO", "TOV")
    threes = _num(raw, "FG3M")
    return {
        "Points": points,
        "Rebounds": rebounds,
        "Assists": assists,
        "Steals": steals,
        "Blocks": blocks,
        "Turnovers": turnovers,
        "3-Pointers Made": threes,
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


def _is_dnp(raw: dict[str, Any]) -> bool:
    comment = str(raw.get("COMMENT") or "").strip()
    minutes = str(raw.get("MIN") or "").strip()
    return bool(comment) and not minutes


def _num(raw: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            try:
                return float(str(value).replace("+", ""))
            except ValueError:
                return 0.0
    return 0.0


def _normalize_matchup(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if " vs. " in text:
        left, right = text.split(" vs. ", 1)
        return f"{right.strip()}@{left.strip()}"
    if " @ " in text:
        left, right = text.split(" @ ", 1)
        return f"{left.strip()}@{right.strip()}"
    return text.replace(" ", "")


def _parse_game_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


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
    return sorted({day + timedelta(days=offset) for day in dates for offset in range(-lookback_days, lookback_days + 1)})


def _empty(skipped: bool = False) -> dict:
    return {
        "provider": "nba_summer_league",
        "skipped": skipped,
        "sports": [],
        "dates": [],
        "games": 0,
        "fetched_rows": 0,
        "imported": 0,
        "errors": [],
    }
