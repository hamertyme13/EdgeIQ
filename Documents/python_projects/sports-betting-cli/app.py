from rich.console import Console

from betting import (
    implied_probability,
    potential_profit,
    total_return,
)
from utils import divider, title

console = Console()


def calculate_bet():
    odds = int(input("Enter American Odds (example -110 or 150): "))
    wager = float(input("Enter Wager: $"))

    probability = implied_probability(odds)
    profit = potential_profit(odds, wager)
    payout = total_return(odds, wager)

    divider()

    console.print(f"[cyan]Implied Probability:[/cyan] {probability:.2%}")
    console.print(f"[green]Potential Profit:[/green] ${profit:.2f}")
    console.print(f"[yellow]Total Return:[/yellow] ${payout:.2f}")

    divider()


def main():
    while True:
        title()

        print("1. Calculate Bet")
        print("2. Exit")

        choice = input("\nChoose an option: ")

        if choice == "1":
            calculate_bet()
        elif choice == "2":
            print("Goodbye!")
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()