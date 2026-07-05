from rich.console import Console

from tracker import (
    get_stats,
    save_bet,
    view_bets   
)

from betting import (
    implied_probability,
    potential_profit,
    total_return,
)
from analytics import get_dashboard
from utils import divider, title
from rich.table import Table

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
def add_bet():

    sport = input("Sport: ")
    game = input("Game: ")
    bet = input("Bet Description: ")

    odds = int(input("Odds: "))
    wager = float(input("Wager: $"))

    print()

    while True:
        print("1. Win")
        print("2. Loss")

        result_choice = input("Result: ").strip()

        if result_choice == "1":
            result = "Win"
            profit = potential_profit(odds, wager)
            break

        elif result_choice == "2":
            result = "Loss"
            profit = -wager
            break

        else:
            print("Please enter 1 or 2.")

    save_bet(
        sport,
        game,
        bet,
        odds,
        wager,
        result,
        profit
    )

    print("\nBet Saved!")

def view_record():

    wins, losses, profit = get_stats()

    total_bets = wins + losses

    win_pct = 0

    if total_bets:
        win_pct = (wins / total_bets) * 100

    divider()

    print(f"Record      : {wins}-{losses}")
    print(f"Win %       : {win_pct:.1f}%")
    print(f"Net Profit  : ${profit:.2f}")

    divider()

def main():
    while True:
        title()

        print("1. Calculate Bet")
        print("2. Add Bet")
        print("3. View Record")
        print("4. View Bet History")
        print("5. View Dashboard")
        print("6. Exit")

        choice = input("\nChoose an option: ")

        if choice == "1":
            calculate_bet()
        elif choice == "2":
            add_bet()
        elif choice == "3":
            view_record()
        elif choice == "4":
            view_bets()
        elif choice == "5":
            dashboard()
        elif choice == "6":
            print("Exiting...")
            break
            


if __name__ == "__main__":
    main()

def dashboard():

    stats = get_dashboard()

    if stats is None:
        print("No bets found.")
        return

    table = Table(title="Betting Dashboard")

    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Starting Bankroll", f"${stats['starting_bankroll']:.2f}")
    table.add_row("Current Bankroll", f"${stats['bankroll']:.2f}")
    table.add_row("Record", stats["record"])

    total = stats["wins"] + stats["losses"]

    if total:
        pct = stats["wins"] / total * 100
    else:
        pct = 0

    table.add_row("Win %", f"{pct:.1f}%")
    table.add_row("Total Wagered", f"${stats['wagered']:.2f}")
    table.add_row("Net Profit", f"${stats['profit']:.2f}")
    table.add_row("ROI", f"{stats['roi']:.2f}%")
    table.add_row("Average Bet", f"${stats['average']:.2f}")
    table.add_row("Largest Win", f"${stats['largest_win']:.2f}")
    table.add_row("Largest Loss", f"${stats['largest_loss']:.2f}")

    console.print(table)