import requests
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

    print("\nToday's Games\n")

    for index, game in enumerate(games, start=1):
        print(f"{index}. {game['away_team']} @ {game['home_team']}")

    return games