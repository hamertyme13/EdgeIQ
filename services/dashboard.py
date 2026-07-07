from repository.bet_repository import BetRepository
from config import STARTING_BANKROLL


def get_dashboard(starting_bankroll=STARTING_BANKROLL) -> dict:

    stats = BetRepository().dashboard_stats()

    current_bankroll = (
       starting_bankroll + stats["profit"]
   )

    stats["bankroll"] = current_bankroll
    stats["record"] = (
          f"{stats['wins']}-{stats['losses']}"
    )
    stats["starting_bankroll"] = starting_bankroll

    return stats