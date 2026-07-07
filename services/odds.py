import requests

from rich.console import Console
from rich.table import Table

from config import API_KEY, SPORT

BASE_URL = "https://api.the-odds-api.com/v4/sports"

console = Console()


def get_games():
    url = (
        f"{BASE_URL}/{SPORT}/odds"
        f"?apiKey={API_KEY}"
        "&regions=us"
        "&markets=h2h"
        "&oddsFormat=american"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        console.print(f"\n[red]Error retrieving odds:[/red] {e}")
        return []

def display_games():

    games = get_games()

    if not games:
        console.print("\n[yellow]No games available right now. Check your API key or try again later.[/yellow]")
        return

    console.print("\nToday's Games\n")

    for i, game in enumerate(games, start=1):
        console.print(f"{i}. {game['away_team']} @ {game['home_team']}")

    console.print()

    selection = input("Choose game: ")

    try:
        selection = int(selection)
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
