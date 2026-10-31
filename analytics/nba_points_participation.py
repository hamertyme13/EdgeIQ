"""Participation gate for zero-point NBA history rows."""

from __future__ import annotations

from math import isfinite


def nba_points_participation_confirmed(row: dict) -> bool:
    """A score of zero needs positive verified minutes or shooting attempts."""
    try:
        if float(row["actual"]) != 0:
            return True
    except (KeyError, TypeError, ValueError):
        return False
    for field, ceiling in (("verified_minutes", 65),
                           ("verified_field_goals_attempted", 60),
                           ("verified_free_throws_attempted", 60)):
        try:
            value = float(row[field])
        except (KeyError, TypeError, ValueError):
            continue
        if isfinite(value) and 0 < value <= ceiling:
            return True
    return False
