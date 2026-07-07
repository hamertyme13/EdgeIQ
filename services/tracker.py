from rich.console import Console
from rich.table import Table
from models.bet import Bet
from repository.bet_repository import BetRepository

console = Console()


def save_bet(bet: Bet) -> None:
    BetRepository().save(bet)

def get_stats() -> tuple[int, int, float]:
    stats = BetRepository().dashboard_stats()
    return stats["wins"], stats["losses"], stats["profit"]

def view_bets():

    table = Table(title="Bet History")

    table.add_column("Sport")
    table.add_column("Game")
    table.add_column("Bet")
    table.add_column("Odds", justify="right")
    table.add_column("Wager", justify="right")
    table.add_column("Result")
    table.add_column("Profit", justify="right")

    bets = BetRepository().get_all()

    for bet in bets:

        table.add_row(
            bet.sport,
            bet.game,
            bet.description,
            str(bet.odds),
            f"${bet.wager:.2f}",
            bet.result,
            f"${bet.profit:.2f}",
        )

    console.print(table)
