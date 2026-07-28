import os
import re

from rich.console import Console
from rich.table import Table

from config import SPORT
from data.providers.cache import get_json

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

console = Console()


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
    for bookmaker in game.get("bookmakers") or []:
        for market in bookmaker.get("markets") or []:
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes") or []:
                try:
                    prices.setdefault(str(outcome.get("name") or ""), []).append(int(outcome["price"]))
                except (KeyError, TypeError, ValueError):
                    continue
    consensus = {
        team: round(sum(team_prices) / len(team_prices))
        for team, team_prices in prices.items()
        if team and team_prices
    }
    return {
        "event_id": game.get("id", ""),
        "away_team": game.get("away_team", ""),
        "home_team": game.get("home_team", ""),
        "commence_time": game.get("commence_time", ""),
        "consensus": consensus,
        "best_prices": {team: max(team_prices) for team, team_prices in prices.items() if team_prices},
        "sportsbook_count": len(game.get("bookmakers") or []),
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
    return {token for token in tokens if token}


def _short_team(team: str) -> str:
    tokens = _team_tokens(team)
    acronyms = [token.upper() for token in tokens if 2 <= len(token) <= 3]
    return sorted(acronyms, key=lambda token: (-len(token), token))[0] if acronyms else team

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
