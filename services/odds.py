
import requests

from rich.console import Console
from rich.table import Table

from config import API_KEY, SPORT

BASE_URL = "https://api.the-odds-api.com/v4/sports"


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
        print(f"\nError retrieving odds: {e}")
        return []

def display_games():

    games = get_games()

    if not games:
        return

    print("\nToday's Games\n")

    for i, game in enumerate(games, start=1):
        print(f"{i}. {game['away_team']} @ {game['home_team']}")

    print()

    selection = input("Choose game: ")

    try:
        selection = int(selection)
    except ValueError:
        print("Please enter a valid number.")
        return

    if 1 <= selection <= len(games):
        display_game_odds(games[selection - 1])
    else:
        print("Invalid selection.")

console = Console()


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