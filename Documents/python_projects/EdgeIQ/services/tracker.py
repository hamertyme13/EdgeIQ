import csv
import os
from datetime import datetime
from rich.console import Console
from rich.table import Table
from config import DATA_FILE

console = Console()

FILE_NAME = DATA_FILE


def initialize_csv():
    os.makedirs("data", exist_ok=True)

    if not os.path.exists(FILE_NAME):
        with open(FILE_NAME, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([
                "Date",
                "Sport",
                "Game",
                "Bet",
                "Odds",
                "Wager",
                "Result",
                "Profit"
            ])


def save_bet(sport, game, bet, odds, wager, result, profit):
    initialize_csv()

    with open(FILE_NAME, "a", newline="") as file:
        writer = csv.writer(file)

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d"),
            sport,
            game,
            bet,
            odds,
            wager,
            result,
            round(profit, 2)
        ])

def get_stats() -> tuple[int, int, float]:
    initialize_csv()

    wins = 0
    losses = 0
    profit = 0

    with open(FILE_NAME) as file:
        reader = csv.DictReader(file)

        for row in reader:

            if row["Result"] == "Win":
                wins += 1
            elif row["Result"] == "Loss":
                losses += 1

            profit += float(row["Profit"])

    return wins, losses, profit

def view_bets():

    initialize_csv()

    table = Table(title="Bet History")

    table.add_column("Date")
    table.add_column("Sport")
    table.add_column("Game")
    table.add_column("Bet")
    table.add_column("Odds", justify="right")
    table.add_column("Wager", justify="right")
    table.add_column("Result")
    table.add_column("Profit", justify="right")

    with open(FILE_NAME) as file:

        reader = csv.DictReader(file)

        for row in reader:

            table.add_row(
                row["Date"],
                row["Sport"],
                row["Game"],
                row["Bet"],
                row["Odds"],
                f"${float(row['Wager']):.2f}",
                row["Result"],
                f"${float(row['Profit']):.2f}"
            )

    console.print(table)