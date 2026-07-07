from rich.console import Console
from rich.table import Table

from analytics.ev import print_ev
from models.bet import Bet
from repository.database import initialize_database
from services.betting import implied_probability, potential_profit, total_return
from services.dashboard import get_dashboard
from services.entry_workflow import run_entry_workflow
from services.odds import display_games
from services.probability import choose_probability
from services.prop_workflow import run_prop_builder
from services.tracker import get_stats, save_bet, view_bets
from utils.display import divider, title

console = Console()


def ev_calculator():

    while True:
        try:
            odds = int(input("American Odds: "))
            break
        except ValueError:
            console.print("[red]Please enter a valid integer.[/red]")

    projection = choose_probability()

    print_ev(odds, projection)


def calculate_bet():

    while True:
        try:
            odds = int(input("Enter American Odds (example -110 or 150): "))
            break
        except ValueError:
            console.print("[red]Please enter a valid integer.[/red]")

    while True:
        try:
            wager = float(input("Enter Wager: $"))
            break
        except ValueError:
            console.print("[red]Please enter a valid amount.[/red]")

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

    while True:
        try:
            odds = int(input("Odds: "))
            break
        except ValueError:
            console.print("[red]Please enter a valid integer.[/red]")

    while True:
        try:
            wager = float(input("Wager: $"))
            break
        except ValueError:
            console.print("[red]Please enter a valid amount.[/red]")

    console.print()

    while True:
        console.print("1. Win")
        console.print("2. Loss")
        console.print("3. Push")

        result_choice = input("Result: ").strip()

        if result_choice == "1":
            result = "Win"
            profit = potential_profit(odds, wager)
            break

        elif result_choice == "2":
            result = "Loss"
            profit = -wager
            break

        elif result_choice == "3":
            result = "Push"
            profit = 0.0
            break

        else:
            console.print("[red]Please enter 1, 2, or 3.[/red]")

    bet_record = Bet(
        sport=sport,
        game=game,
        description=bet,
        odds=odds,
        wager=wager,
        result=result,
        profit=profit
    )

    save_bet(bet_record)

    console.print("\nBet Saved!")


def view_record():

    wins, losses, profit = get_stats()

    total_bets = wins + losses

    win_pct = 0

    if total_bets:
        win_pct = (wins / total_bets) * 100

    divider()

    console.print(f"Record      : {wins}-{losses}")
    console.print(f"Win %       : {win_pct:.1f}%")
    console.print(f"Net Profit  : ${profit:.2f}")

    divider()


def dashboard():

    stats = get_dashboard()

    if stats is None:
        console.print("No bets found.")
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


def main():
    while True:

        console.print("1. 🎯 Single Prop Analysis")
        console.print("2. 🧾 Multi-Prop Entry Builder")
        console.print("3. Calculate Bet")
        console.print("4. Add Bet")
        console.print("5. View Record")
        console.print("6. View Bet History")
        console.print("7. View Dashboard")
        console.print("8. Today's Games")
        console.print("9. EV Calculator")
        console.print("10. Exit")

        choice = input("\nChoose an option: ")

        if choice == "1":
            run_prop_builder()
        elif choice == "2":
            run_entry_workflow()
        elif choice == "3":
            calculate_bet()
        elif choice == "4":
            add_bet()
        elif choice == "5":
            view_record()
        elif choice == "6":
            view_bets()
        elif choice == "7":
            dashboard()
        elif choice == "8":
            display_games()
        elif choice == "9":
            ev_calculator()
        elif choice == "10":
            console.print("Exiting...")
            break


if __name__ == "__main__":
    initialize_database()
    title()
    main()
