import os
import re
import threading
import time
from statistics import median
from typing import Any
from urllib.parse import urlencode

from rich.console import Console
from rich.table import Table

from config import SPORT
from data.providers.cache import get_json
from services.betting import implied_probability
from utils.entity_normalization import canonical_person_key

BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORT_KEYS = {
    "WNBA": "basketball_wnba",
    "NBA": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
    "NCAAF": "americanfootball_ncaaf",
    "NCAAM": "basketball_ncaab",
}
DFS_BOOKS = {"prizepicks", "underdog", "pick6", "betr_us_dfs"}
DEFAULT_PROP_BOOKMAKERS = (
    "draftkings",
    "fanduel",
    "betmgm",
    "williamhill_us",
    "fanatics",
    "prizepicks",
    "underdog",
    "pick6",
)
PROP_MARKETS = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "threes": "player_threes",
    "three pointers made": "player_threes",
    "3 pointers made": "player_threes",
    "blocks": "player_blocks",
    "steals": "player_steals",
    "blocks steals": "player_blocks_steals",
    "turnovers": "player_turnovers",
    "points rebounds assists": "player_points_rebounds_assists",
    "pra": "player_points_rebounds_assists",
    "points rebounds": "player_points_rebounds",
    "points assists": "player_points_assists",
    "rebounds assists": "player_rebounds_assists",
    "fantasy points": "player_fantasy_points",
    "pass yards": "player_pass_yds",
    "passing yards": "player_pass_yds",
    "pass touchdowns": "player_pass_tds",
    "passing touchdowns": "player_pass_tds",
    "pass attempts": "player_pass_attempts",
    "pass completions": "player_pass_completions",
    "passing completions": "player_pass_completions",
    "interceptions": "player_pass_interceptions",
    "receptions": "player_receptions",
    "receiving yards": "player_reception_yds",
    "rush yards": "player_rush_yds",
    "rushing yards": "player_rush_yds",
    "rush attempts": "player_rush_attempts",
    "rushing attempts": "player_rush_attempts",
    "rush receiving yards": "player_rush_reception_yds",
    "passing rushing yards": "player_pass_rush_yds",
    "hits": "batter_hits",
    "total bases": "batter_total_bases",
    "rbis": "batter_rbis",
    "runs": "batter_runs_scored",
    "hits runs rbis": "batter_hits_runs_rbis",
    "home runs": "batter_home_runs",
    "batter strikeouts": "batter_strikeouts",
    "pitcher strikeouts": "pitcher_strikeouts",
    "strikeouts": "pitcher_strikeouts",
    "pitching outs": "pitcher_outs",
    "outs recorded": "pitcher_outs",
    "shots on goal": "player_shots_on_goal",
    "blocked shots": "player_blocked_shots",
    "goals": "player_goals",
    "goalie saves": "player_total_saves",
    "saves": "player_total_saves",
    "shots": "player_shots",
    "shots on target": "player_shots_on_target",
}

console = Console()
_INTERACTIVE_CACHE_SECONDS = 30
_INTERACTIVE_RESPONSE_CACHE: dict[tuple[int, str], tuple[float, Any]] = {}
_INTERACTIVE_RESPONSE_LOCK = threading.Lock()


def _interactive_timeout() -> int:
    return max(1, min(10, int(os.getenv("EDGEIQ_ODDS_INTERACTIVE_TIMEOUT_SECONDS", "3"))))


def _interactive_json(url: str, *, cache_key: str, ttl_seconds: int):
    key = (id(get_json), cache_key)
    now = time.monotonic()
    with _INTERACTIVE_RESPONSE_LOCK:
        cached = _INTERACTIVE_RESPONSE_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
    response = get_json(
        url,
        cache_key=cache_key,
        timeout=_interactive_timeout(),
        ttl_seconds=ttl_seconds,
        retries=0,
    )
    with _INTERACTIVE_RESPONSE_LOCK:
        _INTERACTIVE_RESPONSE_CACHE[key] = (now + _INTERACTIVE_CACHE_SECONDS, response)
    return response


def get_games(sport: str | None = None) -> list[dict]:
    api_key = os.getenv("ODDS_API_KEY", "").strip()
    if not api_key:
        return []
    sport_key = SPORT_KEYS.get(str(sport or "").upper(), SPORT)
    url = (
        f"{BASE_URL}/{sport_key}/odds"
        f"?apiKey={api_key}"
        "&regions=us"
        "&markets=h2h"
        "&oddsFormat=american"
    )
    try:
        data = get_json(
            url,
            cache_key=f"{BASE_URL}/{sport_key}/odds?regions=us&markets=h2h&oddsFormat=american",
            timeout=10,
            ttl_seconds=120,
        ).data
    except RuntimeError as e:
        console.print(f"\n[red]Error retrieving odds:[/red] {e}")
        return []
    return data if isinstance(data, list) else []


def verify_connection() -> dict:
    api_key = os.getenv("ODDS_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "sports": 0, "message": "ODDS_API_KEY is not configured."}
    url = f"{BASE_URL}/?{urlencode({'apiKey': api_key})}"
    try:
        response = get_json(
            url,
            cache_key=f"{BASE_URL}/sports-verification",
            timeout=8,
            ttl_seconds=900,
            retries=1,
        )
    except RuntimeError as exc:
        return {"ok": False, "sports": 0, "message": str(exc)}
    sports = response.data if isinstance(response.data, list) else []
    supported = sorted({
        label for label, key in SPORT_KEYS.items()
        if any(str(row.get("key") or "") == key and bool(row.get("active", True)) for row in sports)
    })
    return {
        "ok": bool(sports),
        "sports": len(sports),
        "supported_active_sports": supported,
        "stale": response.stale,
        "age_seconds": response.age_seconds,
        "message": "The Odds API connection is verified." if sports else "The Odds API returned no sports.",
    }


def get_events(sport: str) -> list[dict]:
    api_key = os.getenv("ODDS_API_KEY", "").strip()
    if not api_key:
        return []
    sport_key = SPORT_KEYS.get(str(sport or "").upper())
    if not sport_key:
        return []
    query = urlencode({"apiKey": api_key, "dateFormat": "iso"})
    url = f"{BASE_URL}/{sport_key}/events?{query}"
    cache_key = f"{BASE_URL}/{sport_key}/events?dateFormat=iso"
    try:
        response = _interactive_json(url, cache_key=cache_key, ttl_seconds=120)
    except RuntimeError:
        return []
    return response.data if isinstance(response.data, list) else []


def get_player_prop_consensus(
    player: str,
    stat: str,
    sport: str,
    game: str,
    line: float,
    direction: str = "Over",
    team: str = "",
) -> dict:
    api_key = os.getenv("ODDS_API_KEY", "").strip()
    if not api_key:
        return _unavailable_prop_market(
            player,
            stat,
            line,
            configured=False,
            reason="Add ODDS_API_KEY to connect multi-book player odds.",
        )
    sport_key = SPORT_KEYS.get(str(sport or "").upper())
    market_key = prop_market_key(stat)
    if not sport_key:
        return _unavailable_prop_market(
            player,
            stat,
            line,
            configured=True,
            reason=f"Multi-book player odds are not configured for {sport or 'this sport'}.",
        )
    if not market_key:
        return _unavailable_prop_market(
            player,
            stat,
            line,
            configured=True,
            reason=f"No supported sportsbook market mapping exists for {stat}.",
        )
    matchup = _complete_matchup(game, team)
    if len(_matchup_team_tokens(matchup)) < 2:
        return _unavailable_prop_market(
            player,
            stat,
            line,
            configured=True,
            reason="A complete matchup is required to retrieve exact player odds.",
            market_key=market_key,
        )
    event = find_event(matchup, sport, get_events(sport))
    if event is None:
        return _unavailable_prop_market(
            player,
            stat,
            line,
            configured=True,
            reason="The matchup could not be matched to a current sportsbook event.",
        )
    bookmakers = _prop_bookmakers()
    query = urlencode({
        "apiKey": api_key,
        "bookmakers": ",".join(bookmakers),
        "markets": market_key,
        "oddsFormat": "american",
        "dateFormat": "iso",
        "includeMultipliers": "true",
    })
    event_id = str(event.get("id") or "")
    url = f"{BASE_URL}/{sport_key}/events/{event_id}/odds?{query}"
    cache_query = urlencode({
        "bookmakers": ",".join(bookmakers),
        "markets": market_key,
        "oddsFormat": "american",
        "dateFormat": "iso",
        "includeMultipliers": "true",
    })
    cache_key = f"{BASE_URL}/{sport_key}/events/{event_id}/odds?{cache_query}"
    try:
        response = _interactive_json(
            url,
            cache_key=cache_key,
            ttl_seconds=max(60, int(os.getenv("EDGEIQ_ODDS_CACHE_SECONDS", "180"))),
        )
    except RuntimeError:
        return _unavailable_prop_market(
            player,
            stat,
            line,
            configured=True,
            reason="The multi-book odds provider is temporarily unavailable.",
            event=event,
            market_key=market_key,
        )
    if not isinstance(response.data, dict):
        return _unavailable_prop_market(
            player,
            stat,
            line,
            configured=True,
            reason="No player odds were returned for this event.",
            event=event,
            market_key=market_key,
        )
    return summarize_player_prop_market(
        response.data,
        player=player,
        stat=stat,
        line=line,
        direction=direction,
        stale=response.stale,
        age_seconds=response.age_seconds,
    )


def prop_market_key(stat: object) -> str:
    return PROP_MARKETS.get(_stat_key(stat), "")


def find_event(game: str, sport: str, events: list[dict] | None = None) -> dict | None:
    candidates = events if events is not None else get_events(sport)
    requested = _matchup_team_tokens(game)
    if len(requested) < 2:
        return None
    for row in candidates:
        away = _team_tokens(row.get("away_team", ""))
        home = _team_tokens(row.get("home_team", ""))
        if (requested[0] & away and requested[1] & home) or (
            requested[0] & home and requested[1] & away
        ):
            return row
    return None


def summarize_player_prop_market(
    event: dict,
    *,
    player: str,
    stat: str,
    line: float,
    direction: str = "Over",
    stale: bool = False,
    age_seconds: int = 0,
) -> dict:
    market_key = prop_market_key(stat)
    player_key = canonical_person_key(player)
    target_line = float(line)
    sportsbook_rows: list[dict[str, Any]] = []
    dfs_offers: list[dict[str, Any]] = []
    last_updates: list[str] = []
    for bookmaker in event.get("bookmakers") or []:
        book_key = str(bookmaker.get("key") or "")
        title = str(bookmaker.get("title") or book_key)
        outcomes: list[dict] = []
        for market in bookmaker.get("markets") or []:
            if str(market.get("key") or "") != market_key:
                continue
            if market.get("last_update"):
                last_updates.append(str(market["last_update"]))
            outcomes.extend(market.get("outcomes") or [])
        matched = [
            outcome for outcome in outcomes
            if canonical_person_key(_outcome_player(outcome)) == player_key
            and _same_line(outcome.get("point"), target_line)
        ]
        sides = {
            str(outcome.get("name") or "").strip().lower(): outcome
            for outcome in matched
            if str(outcome.get("name") or "").strip().lower() in {"over", "under", "higher", "lower"}
        }
        over = sides.get("over") or sides.get("higher")
        under = sides.get("under") or sides.get("lower")
        if book_key in DFS_BOOKS:
            if over or under:
                dfs_offers.append({
                    "bookmaker": title,
                    "bookmaker_key": book_key,
                    "platform": _dfs_platform(book_key, title),
                    "line": target_line,
                    "over": _selection_payload(over),
                    "under": _selection_payload(under),
                    "indicative": True,
                })
            continue
        if not over or not under:
            continue
        try:
            over_odds = int(float(over["price"]))
            under_odds = int(float(under["price"]))
        except (KeyError, TypeError, ValueError):
            continue
        over_implied = implied_probability(over_odds)
        under_implied = implied_probability(under_odds)
        total = over_implied + under_implied
        if total <= 0:
            continue
        sportsbook_rows.append({
            "bookmaker": title,
            "bookmaker_key": book_key,
            "over_odds": over_odds,
            "under_odds": under_odds,
            "over_probability": round((over_implied / total) * 100.0, 2),
            "under_probability": round((under_implied / total) * 100.0, 2),
            "hold": round((total - 1.0) * 100.0, 2),
        })
    fair_over = median([row["over_probability"] for row in sportsbook_rows]) if sportsbook_rows else None
    fair_under = 100.0 - fair_over if fair_over is not None else None
    selected_direction = "Under" if str(direction).strip().lower() in {"under", "lower"} else "Over"
    selected_probability = fair_under if selected_direction == "Under" else fair_over
    book_count = len(sportsbook_rows)
    available = selected_probability is not None
    return {
        "configured": True,
        "available": available,
        "source": "The Odds API",
        "source_type": "multi_book_no_vig",
        "player": player,
        "stat": stat,
        "market_key": market_key,
        "line": target_line,
        "direction": selected_direction,
        "market_probability": round(float(selected_probability), 2) if selected_probability is not None else None,
        "over_probability": round(float(fair_over), 2) if fair_over is not None else None,
        "under_probability": round(float(fair_under), 2) if fair_under is not None else None,
        "book_count": book_count,
        "quality": "strong" if book_count >= 3 else "limited" if book_count else "unavailable",
        "average_hold": (
            round(sum(row["hold"] for row in sportsbook_rows) / book_count, 2)
            if book_count else None
        ),
        "best_over_odds": max((row["over_odds"] for row in sportsbook_rows), default=None),
        "best_under_odds": max((row["under_odds"] for row in sportsbook_rows), default=None),
        "books": sportsbook_rows,
        "dfs_offers": dfs_offers,
        "event": {
            "event_id": event.get("id", ""),
            "away_team": event.get("away_team", ""),
            "home_team": event.get("home_team", ""),
            "commence_time": event.get("commence_time", ""),
        },
        "last_update": max(last_updates, default=""),
        "stale": bool(stale),
        "age_seconds": int(age_seconds or 0),
        "reason": (
            f"Median no-vig probability from {book_count} sportsbook"
            f"{'s' if book_count != 1 else ''} at the exact {target_line:g} line."
            if available
            else "No sportsbook returned paired over and under prices at the exact provider line."
        ),
        "payout_note": (
            "PrizePicks and Underdog selection multipliers are indicative; verify the complete card payout in the provider app."
            if dfs_offers
            else "No DFS selection multiplier was returned for this exact line."
        ),
    }


def find_game_odds(game: str, sport: str, games: list[dict] | None = None) -> dict | None:
    candidates = games if games is not None else get_games(sport)
    requested = _matchup_team_tokens(game)
    if len(requested) < 2:
        return None
    for row in candidates:
        away = _team_tokens(row.get("away_team", ""))
        home = _team_tokens(row.get("home_team", ""))
        if (requested[0] & away and requested[1] & home) or (
            requested[0] & home and requested[1] & away
        ):
            return summarize_game_odds(row)
    return None


def summarize_game_odds(game: dict) -> dict:
    prices: dict[str, list[int]] = {}
    fair_probabilities: dict[str, list[float]] = {}
    bookmaker_keys: list[str] = []
    for bookmaker in game.get("bookmakers") or []:
        book_key = str(bookmaker.get("key") or "")
        for market in bookmaker.get("markets") or []:
            if market.get("key") != "h2h":
                continue
            outcomes = market.get("outcomes") or []
            paired = []
            for outcome in outcomes:
                try:
                    team = str(outcome.get("name") or "")
                    price = int(outcome["price"])
                    prices.setdefault(team, []).append(price)
                    paired.append((team, implied_probability(price)))
                except (KeyError, TypeError, ValueError):
                    continue
            total = sum(probability for _, probability in paired)
            if len(paired) == 2 and total > 0:
                bookmaker_keys.append(book_key)
                for team, probability in paired:
                    fair_probabilities.setdefault(team, []).append(probability / total)
    consensus = {
        team: round(sum(team_prices) / len(team_prices))
        for team, team_prices in prices.items()
        if team and team_prices
    }
    no_vig = {
        team: round(median(team_probabilities) * 100.0, 2)
        for team, team_probabilities in fair_probabilities.items()
        if team and team_probabilities
    }
    predicted_winner = max(no_vig, key=no_vig.get) if no_vig else ""
    win_probability = float(no_vig.get(predicted_winner, 0.0))
    return {
        "event_id": game.get("id", ""),
        "away_team": game.get("away_team", ""),
        "home_team": game.get("home_team", ""),
        "commence_time": game.get("commence_time", ""),
        "consensus": consensus,
        "no_vig_probabilities": no_vig,
        "predicted_winner": predicted_winner,
        "win_probability": round(win_probability, 2),
        "blowout_risk": "Elevated" if win_probability >= 70 else "Moderate" if win_probability >= 62 else "Low",
        "best_prices": {team: max(team_prices) for team, team_prices in prices.items() if team_prices},
        "sportsbook_count": len(game.get("bookmakers") or []),
        "bookmakers": sorted(set(bookmaker_keys)),
        "source": "The Odds API",
    }


def format_consensus_line(odds: dict | None) -> str:
    if not odds or not odds.get("consensus"):
        return "Unavailable"
    away = str(odds.get("away_team") or "Away")
    home = str(odds.get("home_team") or "Home")
    consensus = odds["consensus"]
    values = []
    for team in (away, home):
        if team in consensus:
            price = int(consensus[team])
            values.append(f"{_short_team(team)} {price:+d}")
    return " · ".join(values) if values else "Unavailable"


def _matchup_team_tokens(game: str) -> list[set[str]]:
    parts = re.split(r"\s*(?:@|·|-|\bvs\.?\b|\bat\b)\s*", str(game or ""), maxsplit=1, flags=re.IGNORECASE)
    return [_team_tokens(part) for part in parts if part.strip()]


def _team_tokens(team: object) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(team or "").lower())
    if not words:
        return set()
    city = words[:-1] or words
    tokens = {
        "".join(words),
        "".join(word[0] for word in words),
        "".join(word[0] for word in city),
        "".join(city),
        city[0][:3],
        words[-1],
    }
    aliases = {
        "pho": "phx",
        "lasvegas": "lv",
        "goldenstate": "gs",
        "oklahomacity": "okc",
        "sanantonio": "sa",
        "neworleans": "no",
        "greenbay": "gb",
        "tampabay": "tb",
        "kansascity": "kc",
        "washington": "was",
    }
    for token in tuple(tokens):
        if token in aliases:
            tokens.add(aliases[token])
    # One-letter initials can join unrelated games (for example, MIN/CWS to
    # Milwaukee/Cincinnati), so they are never strong enough for identity.
    return {token for token in tokens if len(token) >= 2}


def _short_team(team: str) -> str:
    tokens = _team_tokens(team)
    acronyms = [token.upper() for token in tokens if 2 <= len(token) <= 3]
    return sorted(acronyms, key=lambda token: (-len(token), token))[0] if acronyms else team


def _stat_key(stat: object) -> str:
    text = str(stat or "").lower()
    text = text.replace("+", " ").replace("&", " and ")
    text = re.sub(r"\bpts?\b", "points", text)
    text = re.sub(r"\brebs?\b", "rebounds", text)
    text = re.sub(r"\basts?\b", "assists", text)
    text = re.sub(r"\brbi\b", "rbis", text)
    text = re.sub(r"\band\b", " ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _complete_matchup(game: object, team: object) -> str:
    game_text = str(game or "").strip()
    team_text = str(team or "").strip()
    if len(_matchup_team_tokens(game_text)) >= 2 or not game_text or not team_text:
        return game_text
    if _team_tokens(game_text) & _team_tokens(team_text):
        return game_text
    return f"{team_text} @ {game_text}"


def _prop_bookmakers() -> tuple[str, ...]:
    configured = [
        value.strip()
        for value in os.getenv("EDGEIQ_ODDS_BOOKMAKERS", "").split(",")
        if value.strip()
    ]
    return tuple(dict.fromkeys(configured or DEFAULT_PROP_BOOKMAKERS))


def _same_line(value: object, target: float) -> bool:
    try:
        return abs(float(str(value)) - float(target)) < 0.001
    except (TypeError, ValueError):
        return False


def _outcome_player(outcome: dict) -> str:
    description = str(outcome.get("description") or "").strip()
    if description:
        return description
    name = str(outcome.get("name") or "").strip()
    return "" if name.lower() in {"over", "under", "higher", "lower"} else name


def _selection_payload(outcome: dict | None) -> dict | None:
    if not outcome:
        return None
    multiplier = outcome.get("multiplier")
    try:
        multiplier = float(multiplier) if multiplier not in (None, "") else None
    except (TypeError, ValueError):
        multiplier = None
    try:
        price = int(float(outcome["price"])) if outcome.get("price") is not None else None
    except (TypeError, ValueError):
        price = None
    return {
        "price": price,
        "multiplier": multiplier,
        "link": outcome.get("link", ""),
        "sid": outcome.get("sid", ""),
    }


def _dfs_platform(book_key: str, title: str) -> str:
    labels = {
        "prizepicks": "PrizePicks",
        "underdog": "Underdog",
        "pick6": "DraftKings Pick6",
        "betr_us_dfs": "Betr Picks",
    }
    return labels.get(book_key, title)


def _unavailable_prop_market(
    player: str,
    stat: str,
    line: float,
    *,
    configured: bool,
    reason: str,
    event: dict | None = None,
    market_key: str = "",
) -> dict:
    event = event or {}
    return {
        "configured": configured,
        "available": False,
        "source": "The Odds API",
        "source_type": "multi_book_no_vig",
        "player": player,
        "stat": stat,
        "market_key": market_key,
        "line": float(line or 0.0),
        "market_probability": None,
        "book_count": 0,
        "quality": "unavailable",
        "books": [],
        "dfs_offers": [],
        "event": {
            "event_id": event.get("id", ""),
            "away_team": event.get("away_team", ""),
            "home_team": event.get("home_team", ""),
            "commence_time": event.get("commence_time", ""),
        },
        "stale": False,
        "age_seconds": 0,
        "reason": reason,
        "payout_note": "No live DFS payout evidence is available for this market.",
    }

def display_games():

    games = get_games()

    if not games:
        console.print("\n[yellow]No games available right now. Check your API key or try again later.[/yellow]")
        return

    console.print("\nToday's Games\n")

    for i, game in enumerate(games, start=1):
        console.print(f"{i}. {game['away_team']} @ {game['home_team']}")

    console.print()

    selection_text = input("Choose game: ")

    try:
        selection = int(selection_text)
    except ValueError:
        console.print("[red]Please enter a valid number.[/red]")
        return

    if 1 <= selection <= len(games):
        display_game_odds(games[selection - 1])
    else:
        console.print("[red]Invalid selection.[/red]")


def display_game_odds(game):

    console.print(
        f"\n[bold cyan]{game['away_team']} @ {game['home_team']}[/bold cyan]\n"
    )

    preferred = {
        "FanDuel",
        "DraftKings",
        "BetMGM",
        "Caesars",
        "ESPN BET"
    }

    for bookmaker in game["bookmakers"]:

        if bookmaker["title"] not in preferred:
            continue

        table = Table(title=bookmaker["title"])

        table.add_column("Team")
        table.add_column("Odds", justify="right")

        outcomes = bookmaker["markets"][0]["outcomes"]

        for outcome in outcomes:

            table.add_row(
                outcome["name"],
                str(outcome["price"])
            )

        console.print(table)
