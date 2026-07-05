from services.betting import implied_probability
from rich.console import Console

def decimal_odds(american_odds: int) -> float:
    """
    Convert American odds to decimal odds.
    """

    if american_odds > 0:
        return (american_odds / 100) + 1

    return (100 / abs(american_odds)) + 1


def expected_value(
    american_odds: int,
    win_probability: float
) -> float:
    """
    Returns expected profit per $1 wagered.

    win_probability should be entered as a decimal:
    0.55 = 55%
    """

    decimal = decimal_odds(american_odds)

    return (
        (win_probability * (decimal - 1))
        - (1 - win_probability)
    )


def sportsbook_probability(american_odds: int):

    return implied_probability(american_odds)

console = Console()


def print_ev(odds, projection):

    sportsbook = sportsbook_probability(odds)

    ev = expected_value(
        odds,
        projection / 100
    )

    console.print()

    console.print(
        f"Sportsbook Probability : {sportsbook:.2%}"
    )

    console.print(
        f"Your Projection        : {projection:.1f}%"
    )

    console.print(
        f"Expected Value         : {ev:.2%}"
    )

    if ev > 0:

        console.print(
            "\n[bold green]✓ Positive EV Bet[/bold green]"
        )

    else:

        console.print(
            "\n[bold red]✗ Negative EV Bet[/bold red]"
        )