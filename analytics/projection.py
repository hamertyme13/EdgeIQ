import math


def edge(line: float, projection: float) -> float:
    """
    Returns the numerical edge between the sportsbook line
    and the user's projection.
    """
    return projection - line


def auto_projection(line: float, trending_count: int = 0) -> float:
    """
    Estimate a projection from the posted line when no user projection exists.

    This is intentionally conservative: it nudges the line upward by a small
    trend-based amount so generated entries can be ranked without claiming a
    true statistical model.
    """
    if line <= 0:
        return 0.0

    trend_pct = min(0.08, max(0.02, math.log10(max(trending_count, 1)) / 100))
    adjustment = max(0.2, min(1.5, line * trend_pct))
    return round(line + adjustment, 1)

def confidence(edge: float) -> float:
    """
    Converts the edge into a simple confidence score.
    """

    score = abs(edge) * 20

    return min(score, 100)
