"""Optional StatsHawk final box score fallback for supported team-sport legs."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from data.providers.cache import get_json
from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.stat_normalization import canonical_stat_label

_BASE = "https://api.statshawk.ai/v1"
_EASTERN = ZoneInfo("America/New_York")
_LEAGUES = {
    "WNBA": "wnba", "NBA": "nba", "NCAAM": "ncaam", "NCAAW": "ncaaw",
    "MLB": "mlb", "NFL": "nfl", "NCAAF": "ncaaf", "NHL": "nhl",
    "MLS": "mls", "EPL": "epl", "UCL": "ucl",
}
_BASKETBALL = frozenset({"WNBA", "NBA", "NCAAM", "NCAAW"})
_FOOTBALL = frozenset({"NFL", "NCAAF"})
_SOCCER = frozenset({"MLS", "EPL", "UCL"})
_TEAM_NAMES = {
    "WNBA": {
        "Atlanta Dream": "ATL", "Chicago Sky": "CHI", "Connecticut Sun": "CON",
        "Dallas Wings": "DAL", "Golden State Valkyries": "GSV", "Indiana Fever": "IND",
        "Las Vegas Aces": "LVA", "Los Angeles Sparks": "LAS", "Minnesota Lynx": "MIN",
        "New York Liberty": "NYL", "Phoenix Mercury": "PHX", "Portland Fire": "POR",
        "Seattle Storm": "SEA", "Toronto Tempo": "TOR", "Washington Mystics": "WAS",
    },
    "NBA": {
        "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
        "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
        "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
        "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
        "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL",
        "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
        "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
        "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
        "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
        "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
        "Utah Jazz": "UTA", "Washington Wizards": "WAS",
    },
    "MLB": {
        "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
        "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
        "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
        "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
        "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
        "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
        "New York Yankees": "NYY", "Athletics": "ATH", "Oakland Athletics": "ATH",
        "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
        "San Francisco Giants": "SF", "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
        "Tampa Bay Rays": "TB", "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR",
        "Washington Nationals": "WSH",
    },
    "NFL": {
        "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
        "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
        "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
        "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
        "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
        "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
        "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
        "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
        "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
        "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
        "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
    },
    "NHL": {
        "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF",
        "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI",
        "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL",
        "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM", "Florida Panthers": "FLA",
        "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN", "Montreal Canadiens": "MTL",
        "Nashville Predators": "NSH", "New Jersey Devils": "NJD", "New York Islanders": "NYI",
        "New York Rangers": "NYR", "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI",
        "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJS", "Seattle Kraken": "SEA",
        "St. Louis Blues": "STL", "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR",
        "Utah Mammoth": "UTA", "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
        "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
    },
}
_ALIASES = {
    sport: {"".join(char for char in name.upper() if char.isalnum()): code for name, code in names.items()}
    for sport, names in _TEAM_NAMES.items()
}
_ALIASES["WNBA"].update({"LV": "LVA", "LA": "LAS", "NY": "NYL", "GS": "GSV", "WSH": "WAS", "PHO": "PHX"})
_ALIASES["NBA"].update({"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "PHO": "PHX"})
_ALIASES["MLB"].update({"AZ": "ARI", "CHW": "CWS", "OAK": "ATH", "SDP": "SD", "SFG": "SF", "TBR": "TB", "WSH": "WSH"})
_ALIASES["NFL"].update({"JAC": "JAX", "WSH": "WAS", "LVR": "LV", "GNB": "GB", "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB"})
_ALIASES["NHL"].update({"LA": "LAK", "SJ": "SJS", "TB": "TBL", "VEG": "VGK", "UTAH": "UTA"})
_BASKETBALL_MEASURES = {
    "Points": ("pts",), "Rebounds": ("reb",), "Assists": ("ast",),
    "Steals": ("stl",), "Blocks": ("blk",), "Turnovers": ("tov",),
    "3-Pointers Made": ("tpm",), "3-Pointers Attempted": ("tpa",),
    "Field Goals Made": ("fgm",), "Field Goals Attempted": ("fga",),
    "Free Throws Made": ("ftm",), "Free Throws Attempted": ("fta",),
    "2-Pointers Made": ("fgm", "tpm"), "2-Pointers Attempted": ("fga", "tpa"),
    "Offensive Rebounds": ("oreb",), "Defensive Rebounds": ("dreb",),
    "Points + Rebounds + Assists": ("pts", "reb", "ast"),
    "Points + Rebounds": ("pts", "reb"), "Points + Assists": ("pts", "ast"),
    "Rebounds + Assists": ("reb", "ast"), "Steals + Blocks": ("stl", "blk"),
}
_BASEBALL_MEASURES = {
    "At Bats": ("batting", ("ab",)), "Plate Appearances": ("batting", ("pa",)),
    "Hits": ("batting", ("h",)), "Runs": ("batting", ("r",)),
    "RBIs": ("batting", ("rbi",)), "Home Runs": ("batting", ("hr",)),
    "Doubles": ("batting", ("b2",)), "Triples": ("batting", ("b3",)),
    "Total Bases": ("batting", ("total_bases",)), "Walks": ("batting", ("bb",)),
    "Stolen Bases": ("batting", ("sb",)), "Hit By Pitch": ("batting", ("hbp",)),
    "Strikeouts": ("batting", ("so",)),
    "Hits + Runs + RBIs": ("batting", ("h", "r", "rbi")),
    "Outs Recorded": ("pitching", ("outs",)),
    "Pitcher Strikeouts": ("pitching", ("so",)),
    "Earned Runs": ("pitching", ("er",)),
    "Hits Allowed": ("pitching", ("h",)),
    "Pitching Walks": ("pitching", ("bb",)),
    "Pitches": ("pitching", ("pitches",)),
    "Batters Faced": ("pitching", ("bf",)),
}
_FOOTBALL_MEASURES = {
    "Passing Yards": ("passing", ("yards",)), "Passing TDs": ("passing", ("td",)),
    "Passing Attempts": ("passing", ("att",)), "Completions": ("passing", ("cmp",)),
    "Rushing Yards": ("rushing", ("yards",)), "Rush Attempts": ("rushing", ("att",)),
    "Rushing TDs": ("rushing", ("td",)), "Receiving Yards": ("receiving", ("yards",)),
    "Receptions": ("receiving", ("rec",)), "Targets": ("receiving", ("targets",)),
    "Receiving TDs": ("receiving", ("td",)),
    "Extra Points Made": ("kicking", ("xpm",)),
    "Extra Points Attempted": ("kicking", ("xpa",)),
    "Kicking Field Goals Made": ("kicking", ("fgm",)),
    "Kicking Field Goals Attempted": ("kicking", ("fga",)),
    "Longest Field Goal": ("kicking", ("fg_long",)),
    "Kicking Points": ("kicking", ("kicking_points",)),
}
_HOCKEY_MEASURES = {
    "Goals": ("skater", ("goals",)), "Assists": ("skater", ("assists",)),
    "Points": ("skater", ("pts",)), "Shots on Goal": ("skater", ("sog",)),
    "Blocked Shots": ("skater", ("blocks",)), "Hits": ("skater", ("hits",)),
    "Saves": ("goalie", ("saves",)), "Goalie Saves": ("goalie", ("saves",)),
    "Goals Against": ("goalie", ("goals_against",)),
    "Shots Against": ("goalie", ("shots_against",)),
}
_SOCCER_MEASURES = {
    "Goals": ("outfield", ("goals",)), "Assists": ("outfield", ("assists",)),
    "Shots": ("outfield", ("shots",)), "Shots on Target": ("outfield", ("sot",)),
    "Tackles": ("outfield", ("tackles",)), "Passes Attempted": ("outfield", ("passes",)),
    "Saves": ("keeper", ("saves",)),
}


def configured() -> bool:
    return bool(_key())


def refresh_final_stats_for_entries(entries: list[dict], *, max_boxscores: int = 20) -> dict:
    result = {"provider": "statshawk", "skipped": False, "fetched_rows": 0,
              "imported": 0, "contests_checked": 0, "errors": []}
    if not configured():
        return {**result, "skipped": True, "reason": "STATSHAWK_API_KEY is not configured."}
    targets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for entry in entries:
        for prop in entry.get("props") or []:
            sport = str(prop.get("sport") or "").upper()
            game_time = _time(prop.get("game_time"))
            if (sport not in _LEAGUES or not game_time or not prop.get("game")
                    or not prop.get("team") or not _supported_stat(sport, prop.get("stat"))):
                continue
            existing = FinalStatsRepository.find_result(prop)
            if existing and existing.get("status") in {"played", "dnp"}:
                continue
            targets[(sport, game_time.astimezone(_EASTERN).date().isoformat())].append(prop)
    if not targets:
        return {**result, "skipped": True, "reason": "No unresolved supported team-sport legs."}

    rows = []
    checked_by_sport: dict[str, int] = defaultdict(int)
    per_sport_limit = max(1, max_boxscores // len({sport for sport, _ in targets}))
    for (sport, day), props in sorted(targets.items(), key=lambda item: item[0][1], reverse=True):
        if result["contests_checked"] >= max_boxscores:
            break
        if checked_by_sport[sport] >= per_sport_limit:
            continue
        season = int(day[:4]) - (sport in {"NBA", "NCAAM", "NCAAW", "NHL", "EPL", "UCL"} and int(day[5:7]) < 7)
        try:
            schedule = _request(
                f"/competitions/{_LEAGUES[sport]}/editions/{season}/games?{urlencode({'date': day})}",
                ttl_seconds=120,
            )
        except RuntimeError as exc:
            result["errors"].append(f"{sport} {day}: {exc}")
            continue
        for contest in (schedule.get("data") or {}).get("items") or []:
            if result["contests_checked"] >= max_boxscores or checked_by_sport[sport] >= per_sport_limit:
                break
            matching = [prop for prop in props if _same_game(prop, contest, sport, day)]
            contest_id = str(contest.get("id") or "")
            if not matching or not contest_id or str(contest.get("status") or "").lower() != "final":
                continue
            result["contests_checked"] += 1
            checked_by_sport[sport] += 1
            try:
                boxscore = _request(f"/contests/{contest_id}/boxscore")
            except RuntimeError as exc:
                result["errors"].append(f"{sport} {day} box score: {exc}")
                continue
            data = boxscore.get("data") or {}
            if not data.get("finalized") or str((data.get("contest") or {}).get("id") or "") != contest_id:
                continue
            for prop in matching:
                row = _final_row(prop, contest, data, sport, day)
                if row:
                    rows.append(row)
    result["fetched_rows"] = len(rows)
    result["imported"] = FinalStatsRepository.upsert_many(rows) if rows else 0
    return result


def _request(path: str, *, ttl_seconds: int = 3600) -> dict:
    token = _key()
    cache_key = "statshawk:" + hashlib.sha256(token.encode()).hexdigest()[:16] + ":" + path
    try:
        response = get_json(
            _BASE + path, cache_key=cache_key,
            headers={"X-API-Key": token, "Accept": "application/json"},
            timeout=10, ttl_seconds=ttl_seconds, retries=0,
        )
    except RuntimeError as exc:
        raise RuntimeError("StatsHawk data could not be refreshed") from exc
    if response.stale or not isinstance(response.data, dict):
        raise RuntimeError("StatsHawk returned stale or invalid data")
    return response.data


def _key() -> str:
    return os.getenv("STATSHAWK_API_KEY", "").strip()


def _time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _same_game(prop: dict, contest: dict, sport: str, day: str) -> bool:
    kickoff = _time(contest.get("kickoff"))
    scheduled = _time(prop.get("game_time"))
    if (not kickoff or not scheduled or abs(kickoff - scheduled) > timedelta(hours=2)
            or kickoff.astimezone(_EASTERN).date().isoformat() != day):
        return False
    provider_game = f"{contest.get('away_team_name') or ''} @ {contest.get('home_team_name') or ''}"
    aliases = _ALIASES.get(sport, {})
    return canonical_matchup_key(prop.get("game"), aliases) == canonical_matchup_key(provider_game, aliases)


def _final_row(prop: dict, contest: dict, boxscore: dict, sport: str, day: str) -> dict | None:
    player_key = canonical_person_key(prop.get("player"))
    aliases = _ALIASES.get(sport, {})
    team_key = canonical_matchup_key(prop.get("team"), aliases)
    for line in boxscore.get("lines") or []:
        if not player_key or canonical_person_key(line.get("person_name")) != player_key:
            continue
        team_id = line.get("team")
        team_name = (contest.get("home_team_name") if team_id == contest.get("home_team")
                     else contest.get("away_team_name") if team_id == contest.get("away_team") else "")
        if not team_name or (team_key and team_key != canonical_matchup_key(team_name, aliases)):
            continue
        value = _stat_value(sport, prop.get("stat"), line.get("phases") or [])
        if value is None:
            continue
        return {
            "player": prop["player"], "team": prop.get("team") or team_name,
            "sport": sport, "stat": canonical_stat_label(prop.get("stat")),
            "game": prop["game"], "game_date": day, "actual": value,
            "status": "played", "source": "statshawk", "player_provider": "statshawk",
            "provider_player_id": str(line.get("person") or ""),
        }
    return None


def _played(measures: dict, field: str = "min") -> bool:
    try:
        return float(measures.get(field)) > 0
    except (TypeError, ValueError):
        return False


def _supported_stat(sport: str, stat: object) -> bool:
    label = canonical_stat_label(stat)
    if sport in _BASKETBALL:
        return label in _BASKETBALL_MEASURES
    if sport == "MLB":
        return label in _BASEBALL_MEASURES or label == "Singles"
    if sport in _FOOTBALL:
        return label in _FOOTBALL_MEASURES or label in {
            "Rush + Rec Yards", "Rush + Rec TDs", "Pass + Rush Yards", "Pass + Rush TDs",
        } or (label == "Interceptions" and "thrown" in str(stat).lower())
    if sport == "NHL":
        return label in _HOCKEY_MEASURES
    return sport in _SOCCER and label in _SOCCER_MEASURES


def _stat_value(sport: str, stat: object, phases: list[dict]) -> float | None:
    label = canonical_stat_label(stat)
    by_phase = {str(item.get("phase") or ""): item.get("measures") or {} for item in phases}
    if sport in _BASKETBALL:
        measures = by_phase.get("basketball_player_game") or by_phase.get("basketball") or {}
        if not _played(measures):
            return None
        return _basketball_value(label, measures)
    if sport == "MLB":
        if label == "Singles":
            measures = by_phase.get("batting") or by_phase.get("baseball_batting") or {}
            if not _played(measures, "pa"):
                return None
            values = _values(measures, ("h", "b2", "b3", "hr"))
            return _valid_result(values[0] - sum(values[1:])) if values else None
        mapping = _BASEBALL_MEASURES.get(label)
        if mapping is None:
            return None
        phase, keys = mapping
        measures = by_phase.get(phase) or by_phase.get(f"baseball_{phase}") or {}
        if phase == "batting" and not _played(measures, "pa"):
            return None
        if phase == "pitching" and not (_played(measures, "bf") or _played(measures, "pitches")):
            return None
        return _sum_values(measures, keys)
    if sport in _FOOTBALL:
        mapping = _FOOTBALL_MEASURES.get(label)
        if mapping:
            phase, keys = mapping
            return _sum_values(by_phase.get(phase) or {}, keys)
        if label == "Interceptions" and "thrown" in str(stat).lower():
            return _sum_values(by_phase.get("passing") or {}, ("intc",))
        combinations = {
            "Rush + Rec Yards": (("rushing", "yards"), ("receiving", "yards")),
            "Rush + Rec TDs": (("rushing", "td"), ("receiving", "td")),
            "Pass + Rush Yards": (("passing", "yards"), ("rushing", "yards")),
            "Pass + Rush TDs": (("passing", "td"), ("rushing", "td")),
        }
        parts = combinations.get(label)
        if not parts:
            return None
        values = [_sum_values(by_phase.get(phase) or {}, (key,)) for phase, key in parts]
        return _valid_result(sum(values)) if all(value is not None for value in values) else None
    if sport == "NHL":
        mapping = _HOCKEY_MEASURES.get(label)
        if mapping:
            phase, keys = mapping
            measures = by_phase.get(phase) or {}
            if _played(measures, "toi_seconds"):
                return _sum_values(measures, keys)
        return None
    if sport in _SOCCER:
        mapping = _SOCCER_MEASURES.get(label)
        if mapping:
            phase, keys = mapping
            measures = by_phase.get(phase) or {}
            if _played(measures, "minutes"):
                return _sum_values(measures, keys)
    return None


def _basketball_value(label: str, measures: dict) -> float | None:
    if label == "2-Pointers Made":
        keys = ("fgm", "tpm")
        subtract = True
    elif label == "2-Pointers Attempted":
        keys = ("fga", "tpa")
        subtract = True
    else:
        keys = _BASKETBALL_MEASURES.get(label)
        subtract = False
    values = _values(measures, keys) if keys else None
    if values is None:
        return None
    result = values[0] - values[1] if subtract else sum(values)
    return _valid_result(result)


def _sum_values(measures: dict, keys: tuple[str, ...]) -> float | None:
    values = _values(measures, keys)
    return _valid_result(sum(values)) if values is not None else None


def _values(measures: dict, keys: tuple[str, ...]) -> list[float] | None:
    if any(measures.get(key) is None for key in keys):
        return None
    try:
        values = [float(measures[key]) for key in keys]
    except (TypeError, ValueError):
        return None
    return values if all(value >= 0 and value < float("inf") for value in values) else None


def _valid_result(value: float) -> float | None:
    return round(value, 2) if value >= 0 and value < float("inf") else None
