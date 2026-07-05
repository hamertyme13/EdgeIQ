def implied_probability(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def potential_profit(odds: int, wager: float) -> float:
    if odds > 0:
        return wager * odds / 100
    return wager * 100 / abs(odds)


def total_return(odds: int, wager: float) -> float:
    return wager + potential_profit(odds, wager)