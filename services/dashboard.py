from config import STARTING_BANKROLL
from repository.bet_repository import BetRepository
from repository.repositories.entry_repository import EntryRepository
from repository.repositories.settings_repository import SettingsRepository


def get_starting_bankroll() -> float:
    """Read bankroll from DB, falling back to config/env default."""
    stored = SettingsRepository.get("starting_bankroll")
    if stored:
        try:
            return float(stored)
        except ValueError:
            pass
    return STARTING_BANKROLL


def set_starting_bankroll(amount: float) -> None:
    SettingsRepository.set("starting_bankroll", str(amount))


def get_dashboard(starting_bankroll: float | None = None) -> dict:

    if starting_bankroll is None:
        starting_bankroll = get_starting_bankroll()

    stats = BetRepository().dashboard_stats()
    entry_stats = EntryRepository.financial_stats()

    stats["wins"] += entry_stats["wins"]
    stats["losses"] += entry_stats["losses"]
    stats["pushes"] += entry_stats["pushes"]
    stats["profit"] = round(stats["profit"] + entry_stats["profit"], 2)
    stats["wagered"] = round(stats["wagered"] + entry_stats["wagered"], 2)
    stats["roi"] = round((stats["profit"] / stats["wagered"] * 100) if stats["wagered"] else 0.0, 2)
    stats["pending_entry_exposure"] = entry_stats["pending_exposure"]
    stats["entries"] = entry_stats

    current_bankroll = (
       starting_bankroll + stats["profit"] - entry_stats["pending_exposure"]
   )

    stats["bankroll"] = current_bankroll
    stats["record"] = (
          f"{stats['wins']}-{stats['losses']}"
    )
    stats["starting_bankroll"] = starting_bankroll

    return stats
