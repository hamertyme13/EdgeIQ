from services.odds import get_games

games = get_games()

print(f"Found {len(games)} games.\n")

for game in games:
    print(f"{game['away_team']} @ {game['home_team']}")