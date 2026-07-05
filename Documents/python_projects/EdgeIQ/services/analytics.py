import csv
import os

from config import STARTING_BANKROLL, DATA_FILE

FILE_NAME = DATA_FILE


def get_dashboard(starting_bankroll=STARTING_BANKROLL) -> dict:

    if not os.path.exists(FILE_NAME):
        return None

    wins = 0
    losses = 0

    total_profit = 0
    total_wagered = 0

    wagers = []
    profits = []

    with open(FILE_NAME) as file:

        reader = csv.DictReader(file)

        for row in reader:

            wager = float(row["Wager"])
            profit = float(row["Profit"])

            wagers.append(wager)
            profits.append(profit)

            total_wagered += wager
            total_profit += profit

            if row["Result"] == "Win":
                wins += 1
            else:
                losses += 1

    total_bets = wins + losses

    current_bankroll = starting_bankroll + total_profit

    roi = 0

    if total_wagered:
        roi = (total_profit / total_wagered) * 100

    average_bet = 0

    if wagers:
        average_bet = sum(wagers) / len(wagers)

    return {
        "wins": wins,
        "losses": losses,
        "record": f"{wins}-{losses}",
        "bankroll": current_bankroll,
        "profit": total_profit,
        "wagered": total_wagered,
        "roi": roi,
        "average": average_bet,
        "largest_win": max(profits),
        "largest_loss": min(profits),
        "starting_bankroll": starting_bankroll,
    }