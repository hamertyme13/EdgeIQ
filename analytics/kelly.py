"""
Kelly Criterion bet sizing.

Given the sportsbook odds and your estimated win probability, returns:
  - full Kelly fraction (% of bankroll to wager)
  - half Kelly (conservative recommendation)
  - suggested dollar wager given a bankroll

Formula: f* = (b·p - q) / b
  where b = net odds (profit per $1 wagered), p = win prob, q = 1 - p
"""

from __future__ import annotations


def kelly_fraction(american_odds: int, win_probability: float) -> float:
    """
    Return the full Kelly fraction (0–1) for a bet.

    Args:
        american_odds:   American-style odds (e.g. -110, +150)
        win_probability: Estimated win probability as a decimal (e.g. 0.55)

    Returns:
        Kelly fraction clipped to [0, 1].  Negative values (no edge) → 0.
    """
    if american_odds > 0:
        b = american_odds / 100
    else:
        b = 100 / abs(american_odds)

    p = win_probability
    q = 1 - p

    f = (b * p - q) / b
    return max(0.0, min(1.0, f))


def half_kelly(american_odds: int, win_probability: float) -> float:
    """Return the half-Kelly fraction (conservative standard practice)."""
    return kelly_fraction(american_odds, win_probability) / 2


def suggested_wager(
    american_odds: int,
    win_probability: float,
    bankroll: float,
    use_half: bool = True,
) -> float:
    """
    Return the suggested dollar wager.

    Args:
        american_odds:   Sportsbook odds.
        win_probability: Your estimated win probability (decimal).
        bankroll:        Current bankroll in dollars.
        use_half:        If True, use half-Kelly (recommended default).

    Returns:
        Suggested wager rounded to 2 decimal places.
    """
    fraction = half_kelly(american_odds, win_probability) if use_half else kelly_fraction(american_odds, win_probability)
    return round(fraction * bankroll, 2)


def breakeven_probability(american_odds: int) -> float:
    """
    Return the minimum win probability required to break even at these odds.
    This is simply the implied probability (vig-inclusive).
    """
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return abs(american_odds) / (abs(american_odds) + 100)
