"""ESPN public box-score provider for final player stats."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from data.providers.cache import get_json
from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.entity_normalization import canonical_person_key

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
_SLATE_TIME_ZONE = ZoneInfo("America/New_York")


def refresh_final_stats_for_entries(entries: list[dict], lookback_days: int = 2) -> dict:
    """Fetch ESPN final box scores for the sports/dates represented by entries."""
    sports = sorted({
        str(prop.get("sport", "")).upper()
        for entry in entries
        for prop in entry.get("props", [])
        if str(prop.get("sport", "")).upper() in _SPORT_PATHS
    })
    rows: list[dict] = []
    errors: list[str] = []
    requested_dates: set[date] = set()
    for sport in sports:
        sport_entries = _entries_for_sport(entries, sport)
        sport_dates = _date_window(_entry_dates(sport_entries), lookback_days)
        requested_dates.update(sport_dates)
        for game_date in sport_dates:
            try:
                final_rows = fetch_final_stats(sport, game_date)
                rows.extend(final_rows)
                rows.extend(fetch_missing_entry_dnp_stats(sport_entries, sport, game_date, final_rows))
                rows.extend(fetch_unplayed_entry_stats(sport_entries, sport, game_date))
            except RuntimeError as exc:
                errors.append(f"{sport} {game_date.isoformat()}: {exc}")

    imported = FinalStatsRepository.upsert_many(rows) if rows else 0
    return {
        "provider": "espn",
        "sports": sports,
        "dates": [day.isoformat() for day in sorted(requested_dates)],
        "fetched_rows": len(rows),
        "imported": imported,
        "errors": errors,
    }


def refresh_live_stats_for_entries(entries: list[dict], lookback_days: int = 1) -> dict:
    """Fetch ESPN in-progress box score rows for pending entries."""
    sports = sorted({
        str(prop.get("sport", "")).upper()
        for entry in entries
        for prop in entry.get("props", [])
        if str(prop.get("sport", "")).upper() in _SPORT_PATHS
    })
    dates = _entry_dates(entries)

    rows: list[dict] = []
    errors: list[str] = []
    for sport in sports:
        for game_date in _date_window(dates, lookback_days):
            try:
                rows.extend(fetch_live_stats(sport, game_date))
            except RuntimeError as exc:
                errors.append(f"{sport} {game_date.isoformat()}: {exc}")

    imported = FinalStatsRepository.upsert_many(rows) if rows else 0
    return {
        "provider": "espn_live",
        "sports": sports,
        "dates": [day.isoformat() for day in _date_window(dates, lookback_days)],
        "fetched_rows": len(rows),
        "imported": imported,
        "errors": errors,
    }


def refresh_game_times_for_entries(entries: list[dict], lookback_days: int = 2) -> dict:
    """Fetch ESPN scoreboard start times for the sports/dates represented by entries."""
    sports = sorted({
        str(prop.get("sport", "")).upper()
        for entry in entries
        for prop in entry.get("props", [])
        if str(prop.get("sport", "")).upper() in _SPORT_PATHS
    })
    dates = _entry_dates(entries)

    rows: list[dict] = []
    errors: list[str] = []
    for sport in sports:
        for game_date in _date_window(dates, lookback_days):
            try:
                rows.extend(fetch_game_times(sport, game_date))
            except RuntimeError as exc:
                errors.append(f"{sport} {game_date.isoformat()}: {exc}")

    return {
        "provider": "espn",
        "sports": sports,
        "dates": [day.isoformat() for day in _date_window(dates, lookback_days)],
        "fetched_rows": len(rows),
        "rows": rows,
        "errors": errors,
    }


def fetch_game_times(sport: str, game_date: date) -> list[dict]:
    sport_key = sport.upper()
    path = _SPORT_PATHS.get(sport_key)
    if path is None:
        return []

    scoreboard = _scoreboard(path, game_date)
    rows: list[dict] = []
    for event in scoreboard.get("events", []):
        competition = _first(event.get("competitions", []))
        game_time = event.get("date") or competition.get("date")
        matchup = _event_matchup(event)
        if not matchup or not game_time:
            continue
        rows.append({
            "sport": sport_key,
            "game": matchup,
            "game_time": game_time,
            "game_date": game_date.isoformat(),
            "source": "espn",
        })
    return rows


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
        summary = _summary(path, event_id, cache_variant="final")
        rows.extend(_parse_summary(summary, sport_key, game_date))
    return rows


def fetch_unplayed_entry_stats(entries: list[dict], sport: str, game_date: date) -> list[dict]:
    """Create DNP rows for entry legs whose entire event was postponed or canceled."""
    sport_key = sport.upper()
    path = _SPORT_PATHS.get(sport_key)
    if path is None:
        return []
    scoreboard = _scoreboard(path, game_date)
    rows: list[dict] = []
    for event in scoreboard.get("events", []):
        competition = _first(event.get("competitions", []))
        status = (competition.get("status", {}) if competition else {}).get("type", {})
        status_name = str(status.get("name") or status.get("description") or "").upper()
        if "POSTPON" not in status_name and "CANCEL" not in status_name:
            continue
        matchup = _event_matchup(event)
        for entry in entries:
            for prop in entry.get("props", []):
                if str(prop.get("sport") or "").upper() != sport_key:
                    continue
                if not _prop_matches_event(prop, matchup, game_date):
                    continue
                rows.append(_row(
                    str(prop.get("player") or ""),
                    str(prop.get("team") or ""),
                    sport_key,
                    str(prop.get("stat") or ""),
                    matchup,
                    game_date,
                    0.0,
                    "dnp",
                ))
    return rows


def fetch_missing_entry_dnp_stats(
    entries: list[dict],
    sport: str,
    game_date: date,
    final_rows: list[dict],
) -> list[dict]:
    """Mark a tracked player DNP only after their exact game has a final box score."""
    games = {str(row.get("game") or "") for row in final_rows if row.get("game")}
    players_by_game = {
        game: {
            canonical_person_key(row.get("player"))
            for row in final_rows
            if row.get("game") == game and row.get("player")
        }
        for game in games
    }
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        for prop in entry.get("props", []):
            if str(prop.get("sport") or "").upper() != sport.upper():
                continue
            matching_game = next((game for game in games if _prop_matches_event(prop, game, game_date)), "")
            if not matching_game:
                continue
            player_key = canonical_person_key(prop.get("player"))
            if not player_key or player_key in players_by_game.get(matching_game, set()):
                continue
            stat = str(prop.get("stat") or "").strip()
            key = (player_key, stat.lower(), matching_game)
            if not stat or key in seen:
                continue
            seen.add(key)
            rows.append(_row(
                str(prop.get("player") or ""),
                str(prop.get("team") or ""),
                sport.upper(),
                stat,
                matching_game,
                game_date,
                0.0,
                "dnp",
            ))
    return rows


def _prop_matches_event(prop: dict, matchup: str, game_date: date) -> bool:
    matchup_key = "".join(character for character in matchup.upper() if character.isalnum())
    team_key = "".join(character for character in str(prop.get("team") or "").upper() if character.isalnum())
    opponent_key = "".join(character for character in str(prop.get("game") or "").upper() if character.isalnum())
    if not team_key or not opponent_key or team_key not in matchup_key or opponent_key not in matchup_key:
        return False
    game_time = str(prop.get("game_time") or "").strip()
    if not game_time:
        return True
    try:
        prop_date = datetime.fromisoformat(game_time.replace("Z", "+00:00")).date()
    except ValueError:
        return True
    return abs((prop_date - game_date).days) <= 1


def fetch_live_stats(sport: str, game_date: date) -> list[dict]:
    sport_key = sport.upper()
    path = _SPORT_PATHS.get(sport_key)
    if path is None:
        return []

    scoreboard = _scoreboard(path, game_date, ttl_seconds=45)
    rows: list[dict] = []
    for event in scoreboard.get("events", []):
        competition = _first(event.get("competitions", []))
        status = (competition.get("status", {}) if competition else {}).get("type", {})
        if status.get("completed"):
            continue
        state = str(status.get("state") or "").lower()
        if state not in {"in", "in_progress", "live"}:
            continue
        event_id = event.get("id")
        if not event_id:
            continue
        summary = _summary(path, event_id, ttl_seconds=30)
        rows.extend(_parse_summary(summary, sport_key, game_date, row_status="live"))
    return rows


def _scoreboard(path: str, game_date: date, ttl_seconds: int = 900) -> dict:
    dates = game_date.strftime("%Y%m%d")
    url = f"{_BASE}/{path}/scoreboard?dates={dates}"
    response = get_json(
        url,
        headers=_HEADERS,
        timeout=12,
        ttl_seconds=ttl_seconds,
        browser_fallback=True,
    )
    if getattr(response, "stale", False):
        raise RuntimeError("Official scoreboard refresh failed; the saved schedule is stale and cannot settle entries.")
    return response.data


def _summary(
    path: str,
    event_id: str,
    ttl_seconds: int = 86400,
    cache_variant: str = "",
) -> dict:
    url = f"{_BASE}/{path}/summary?event={event_id}"
    cache_key = f"{url}#{cache_variant}" if cache_variant else None
    return get_json(
        url,
        cache_key=cache_key,
        headers=_HEADERS,
        timeout=12,
        ttl_seconds=ttl_seconds,
        browser_fallback=True,
    ).data


def _parse_summary(summary: dict, sport: str, game_date: date, row_status: str = "played") -> list[dict]:
    if sport in {"WNBA", "NBA"}:
        return _parse_basketball_summary(summary, sport, game_date, row_status=row_status)
    if sport == "MLB":
        return _parse_baseball_summary(summary, game_date, row_status=row_status)
    if sport == "NFL":
        return _parse_football_summary(summary, game_date, row_status=row_status)
    return []


def _parse_football_summary(summary: dict, game_date: date, row_status: str = "played") -> list[dict]:
    matchup = _matchup(summary)
    players: dict[tuple[str, str], dict] = {}
    for team_group in summary.get("boxscore", {}).get("players", []):
        team_abbr = team_group.get("team", {}).get("abbreviation", "")
        for stat_group in team_group.get("statistics", []):
            category = str(stat_group.get("name") or stat_group.get("displayName") or "").lower()
            labels = stat_group.get("names") or stat_group.get("labels") or []
            for athlete_row in stat_group.get("athletes", []):
                athlete = athlete_row.get("athlete", {})
                player = str(athlete.get("displayName") or "").strip()
                if not player:
                    continue
                provider_id = str(athlete.get("id") or athlete.get("uid") or "").strip()
                key = (provider_id or canonical_person_key(player), team_abbr)
                record = players.setdefault(key, {
                    "player": player,
                    "team": team_abbr,
                    "athlete": athlete,
                    "did_not_play": False,
                    "categories": {},
                })
                record["did_not_play"] = bool(record["did_not_play"] or athlete_row.get("didNotPlay"))
                if not athlete_row.get("didNotPlay"):
                    record["categories"][category] = {
                        "stats": _stats_by_label(labels, athlete_row.get("stats", [])),
                        "raw": {str(label).upper(): value for label, value in zip(labels, athlete_row.get("stats", []), strict=False)},
                    }

    rows: list[dict] = []
    for record in players.values():
        player = record["player"]
        team = record["team"]
        if record["did_not_play"] and not record["categories"]:
            player_rows = _football_dnp_rows(player, team, matchup, game_date)
        else:
            player_rows = _football_stat_rows(
                player,
                team,
                matchup,
                game_date,
                record["categories"],
                row_status,
            )
        rows.extend(_with_athlete_identity(player_rows, record["athlete"]))
    return rows


def _football_stat_rows(
    player: str,
    team: str,
    game: str,
    game_date: date,
    categories: dict[str, dict],
    status: str,
) -> list[dict]:
    passing = (categories.get("passing") or {}).get("stats", {})
    passing_raw = (categories.get("passing") or {}).get("raw", {})
    rushing = (categories.get("rushing") or {}).get("stats", {})
    receiving = (categories.get("receiving") or {}).get("stats", {})
    defensive = (categories.get("defensive") or {}).get("stats", {})
    interceptions = (categories.get("interceptions") or {}).get("stats", {})
    kicking = (categories.get("kicking") or {}).get("stats", {})
    kicking_raw = (categories.get("kicking") or {}).get("raw", {})

    values: dict[str, float] = {}
    if passing:
        completions, attempts = _made_attempted(passing_raw.get("C/ATT", "0/0"))
        values.update({
            "Pass Yards": passing.get("YDS", 0.0),
            "Passing Yards": passing.get("YDS", 0.0),
            "Pass TDs": passing.get("TD", 0.0),
            "Passing TDs": passing.get("TD", 0.0),
            "INT": passing.get("INT", 0.0),
            "INTs Thrown": passing.get("INT", 0.0),
            "Interceptions": passing.get("INT", 0.0),
            "Interceptions Thrown": passing.get("INT", 0.0),
            "Completions": completions,
            "Pass Completions": completions,
            "Passing Attempts": attempts,
            "Pass Attempts": attempts,
        })
    if rushing:
        values.update({
            "Rush Yards": rushing.get("YDS", 0.0),
            "Rushing Yards": rushing.get("YDS", 0.0),
            "Rush Attempts": rushing.get("CAR", 0.0),
            "Carries": rushing.get("CAR", 0.0),
            "Rush TDs": rushing.get("TD", 0.0),
            "Rushing TDs": rushing.get("TD", 0.0),
        })
    if receiving:
        values.update({
            "Rec Yards": receiving.get("YDS", 0.0),
            "Receiving Yards": receiving.get("YDS", 0.0),
            "Receptions": receiving.get("REC", 0.0),
            "Targets": receiving.get("TGTS", 0.0),
            "Rec TDs": receiving.get("TD", 0.0),
            "Receiving TDs": receiving.get("TD", 0.0),
        })
    if rushing or receiving:
        rush_yards = rushing.get("YDS", 0.0)
        rec_yards = receiving.get("YDS", 0.0)
        rush_tds = rushing.get("TD", 0.0)
        rec_tds = receiving.get("TD", 0.0)
        values.update({
            "Rush + Rec Yards": rush_yards + rec_yards,
            "Rush+Rec Yards": rush_yards + rec_yards,
            "Rush + Rec TDs": rush_tds + rec_tds,
            "Rush+Rec TDs": rush_tds + rec_tds,
        })
    if defensive:
        total_tackles = defensive.get("TOT", 0.0)
        values.update({
            "Sacks": defensive.get("SACKS", 0.0),
            "Tackles": total_tackles,
            "Tackles + Assists": total_tackles,
        })
    if interceptions:
        values.update({
            "Defensive Interceptions": interceptions.get("INT", 0.0),
            "Interceptions": interceptions.get("INT", 0.0),
        })
    if kicking:
        xp_made, _ = _made_attempted(kicking_raw.get("XP", "0/0"))
        values.update({
            "XP Made": xp_made,
            "Extra Points Made": xp_made,
            "Kicking Points": kicking.get("PTS", 0.0),
        })

    return [_row(player, team, "NFL", stat, game, game_date, actual, status) for stat, actual in values.items()]


def _football_dnp_rows(player: str, team: str, game: str, game_date: date) -> list[dict]:
    stats = [
        "Pass Yards", "Passing Yards", "Pass TDs", "Passing TDs", "INT", "INTs Thrown",
        "Interceptions", "Completions", "Pass Completions", "Passing Attempts", "Pass Attempts",
        "Rush Yards", "Rushing Yards", "Rush Attempts", "Carries", "Rush TDs", "Rushing TDs",
        "Rec Yards", "Receiving Yards", "Receptions", "Targets", "Rec TDs", "Receiving TDs",
        "Rush + Rec Yards", "Rush+Rec Yards", "Rush + Rec TDs", "Rush+Rec TDs", "Sacks",
        "Tackles", "Tackles + Assists",
        "Defensive Interceptions",
        "XP Made", "Extra Points Made", "Kicking Points",
    ]
    return [_row(player, team, "NFL", stat, game, game_date, 0.0, "dnp") for stat in stats]


def _made_attempted(value: Any) -> tuple[float, float]:
    text = str(value or "0/0").strip().replace("-", "/")
    parts = text.split("/", 1)
    if len(parts) != 2:
        return _numeric(text), 0.0
    return _numeric(parts[0]), _numeric(parts[1])


def _parse_baseball_summary(summary: dict, game_date: date, row_status: str = "played") -> list[dict]:
    rows: list[dict] = []
    matchup = _matchup(summary)
    for team_group in summary.get("boxscore", {}).get("players", []):
        team_abbr = team_group.get("team", {}).get("abbreviation", "")
        for stat_group in team_group.get("statistics", []):
            labels = stat_group.get("names") or stat_group.get("labels") or []
            label_keys = {str(label).upper() for label in labels}
            is_pitching = {"IP", "ER", "K"}.issubset(label_keys)
            for athlete_row in stat_group.get("athletes", []):
                athlete = athlete_row.get("athlete", {})
                player = athlete.get("displayName", "")
                if not player or athlete_row.get("didNotPlay"):
                    continue
                stats = _stats_by_label(labels, athlete_row.get("stats", []))
                if is_pitching:
                    rows.extend(_with_athlete_identity(_baseball_pitching_rows(
                        player,
                        team_abbr,
                        matchup,
                        game_date,
                        stats,
                        athlete_row,
                        row_status,
                    ), athlete))
                else:
                    rows.extend(_with_athlete_identity(_baseball_hitting_rows(
                        player,
                        team_abbr,
                        matchup,
                        game_date,
                        stats,
                        row_status,
                    ), athlete))
    return rows


def _baseball_hitting_rows(
    player: str,
    team: str,
    game: str,
    game_date: date,
    stats: dict[str, float],
    status: str,
) -> list[dict]:
    hits = stats.get("H", 0.0)
    runs = stats.get("R", 0.0)
    rbis = stats.get("RBI", 0.0)
    values = {
        "Hits": hits,
        "Runs": runs,
        "RBIs": rbis,
        "Home Runs": stats.get("HR", 0.0),
        "Hits + Runs + RBIs": hits + runs + rbis,
    }
    return [_row(player, team, "MLB", stat, game, game_date, actual, status) for stat, actual in values.items()]


def _baseball_pitching_rows(
    player: str,
    team: str,
    game: str,
    game_date: date,
    stats: dict[str, float],
    athlete_row: dict,
    status: str,
) -> list[dict]:
    outs = _innings_to_outs(stats.get("IP", 0.0))
    earned_runs = stats.get("ER", 0.0)
    strikeouts = stats.get("K", 0.0)
    decision = " ".join(str(note.get("text") or "") for note in athlete_row.get("notes", []))
    won = decision.strip().upper().startswith("W,")
    quality_start = bool(athlete_row.get("starter")) and outs >= 18 and earned_runs <= 3
    fantasy_points = (
        (6 if won else 0)
        + (4 if quality_start else 0)
        - (3 * earned_runs)
        + (3 * strikeouts)
        + outs
    )
    values = {
        "Points": fantasy_points,
        "Pitcher Fantasy Score": fantasy_points,
        "Pitcher Strikeouts": strikeouts,
        "Strikeouts": strikeouts,
        "Pitching Outs": outs,
        "Earned Runs": earned_runs,
    }
    return [_row(player, team, "MLB", stat, game, game_date, actual, status) for stat, actual in values.items()]


def _innings_to_outs(value: Any) -> int:
    try:
        innings = float(value or 0)
    except (TypeError, ValueError):
        return 0
    whole = int(innings)
    partial = int(round((innings - whole) * 10))
    return (whole * 3) + max(0, min(2, partial))


def _parse_basketball_summary(summary: dict, sport: str, game_date: date, row_status: str = "played") -> list[dict]:
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
                    rows.extend(_with_athlete_identity(_dnp_rows(player, team_abbr, sport, matchup, game_date), athlete))
                    continue
                stats = _stats_by_label(labels, athlete_row.get("stats", []))
                rows.extend(_with_athlete_identity(
                    _basketball_stat_rows(player, team_abbr, sport, matchup, game_date, stats, row_status),
                    athlete,
                ))
    return rows


def _basketball_stat_rows(
    player: str,
    team: str,
    sport: str,
    game: str,
    game_date: date,
    stats: dict[str, float],
    status: str = "played",
) -> list[dict]:
    points = stats.get("PTS", 0.0)
    rebounds = stats.get("REB", 0.0)
    assists = stats.get("AST", 0.0)
    steals = stats.get("STL", 0.0)
    blocks = stats.get("BLK", 0.0)
    turnovers = stats.get("TO", 0.0)
    threes = _made_field_goal(stats.get("3PT", 0.0))

    values = {
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
    return [
        _row(player, team, sport, stat, game, game_date, actual, status)
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
        "3-Pointers Made",
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
        "player_provider": "espn",
    }


def _with_athlete_identity(rows: list[dict], athlete: dict) -> list[dict]:
    provider_id = str(athlete.get("id") or athlete.get("uid") or "").strip()
    for row in rows:
        row["provider_player_id"] = provider_id
    return rows


def _stats_by_label(labels: Iterable[str], values: Iterable[Any]) -> dict[str, float]:
    stats: dict[str, float] = {}
    for label, value in zip(labels, values, strict=False):
        key = str(label).upper()
        stats[key] = _made_field_goal(value) if key in {"3PT", "3FG"} else _numeric(value)
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


def _made_field_goal(value: Any) -> float:
    text = str(value or "0").strip()
    if "-" in text:
        text = text.split("-", 1)[0]
    return _numeric(text)


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


def _event_matchup(event: dict) -> str:
    competition = _first(event.get("competitions", []))
    competitors = competition.get("competitors", []) if competition else []
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
    if isinstance(placed_at, str) and placed_at:
        with suppress(ValueError):
            placed_at = datetime.fromisoformat(placed_at.replace("Z", "+00:00"))
    if isinstance(placed_at, datetime):
        if placed_at.tzinfo is None:
            placed_at = placed_at.replace(tzinfo=UTC)
        return placed_at.astimezone(_SLATE_TIME_ZONE).date()
    return date.today()


def _entry_dates(entries: list[dict]) -> list[date]:
    dates: set[date] = set()
    for entry in entries:
        prop_dates: set[date] = set()
        for prop in entry.get("props", []):
            game_time = str(prop.get("game_time") or "").strip()
            if not game_time:
                continue
            try:
                parsed = datetime.fromisoformat(game_time.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                prop_dates.add(parsed.astimezone(_SLATE_TIME_ZONE).date())
            except ValueError:
                continue
        dates.update(prop_dates or {_entry_date(entry)})
    return sorted(dates)


def _entries_for_sport(entries: list[dict], sport: str) -> list[dict]:
    filtered = []
    for entry in entries:
        props = [
            prop for prop in entry.get("props", [])
            if str(prop.get("sport") or "").upper() == sport.upper()
        ]
        if props:
            filtered.append({**entry, "props": props})
    return filtered


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
