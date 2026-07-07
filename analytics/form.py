"""
Recent form weighting.

Adjusts a season-average projection based on the player's last N games,
giving more weight to recent performance.
"""

from __future__ import annotations


def weighted_projection(
    season_avg: float,
    recent_avg: float,
    recent_weight: float = 0.6,
) -> float:
    """
    Blend season average with recent average.

    Args:
        season_avg:     Full-season average for this stat.
        recent_avg:     Average over the last N games (typically 5).
        recent_weight:  Weight given to recent_avg (0–1). Default 0.6.

    Returns:
        Weighted projection.
    """
    season_weight = 1 - recent_weight
    return round(season_avg * season_weight + recent_avg * recent_weight, 2)


def form_signal(recent_avg: float, season_avg: float) -> str:
    """
    Return a human-readable trend label.

    Returns:
        '🔥 Hot', '📈 Above Average', '📊 Average', '📉 Below Average', '❄️ Cold'
    """
    if season_avg == 0:
        return "📊 Average"

    pct = (recent_avg - season_avg) / season_avg * 100

    if pct >= 15:
        return "🔥 Hot"
    elif pct >= 5:
        return "📈 Above Average"
    elif pct >= -5:
        return "📊 Average"
    elif pct >= -15:
        return "📉 Below Average"
    else:
        return "❄️ Cold"
