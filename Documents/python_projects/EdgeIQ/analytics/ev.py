from services.betting import implied_probability
from rich.console import Console

from analytics.recommendation import recommendation, grade

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

    ev_percent = ev * 100

    result = recommendation(ev_percent)

    letter_grade = grade(ev_percent)

    console.rule("[bold cyan]EdgeIQ Analysis[/bold cyan]")

    console.print(
        f"[cyan]Your Estimated Probability:[/cyan] "
        f"{projection:.1f}%"
    )

    console.print(
        f"[yellow]Sportsbook Probability:[/yellow] "
        f"{sportsbook * 100:.1f}%"
    )

    edge = projection - (sportsbook * 100)

    console.print(
        f"[green]Edge:[/green] {edge:+.1f}%"
    )

    console.print(
        f"[bold]Expected Value:[/bold] {ev * 100:+.2f}%"
    )

    console.print(

    )

    console.print(
        f"[bold cyan]Overall Grade:[/bold cyan] [bold]{letter_grade}[/bold]"
    )

    console.print(
        result["action"],
        style=result["color"]
    )

    console.print(result["summary"])

    console.print()

    console.print(
        "[dim]"
        "Remember: Positive EV does not guarantee a win. "
        "It simply means the wager has positive long-term value. Bet responsibly."
        "[/dim]"
    )

    console.rule()