from __future__ import annotations

from dataclasses import dataclass

from utils.stat_normalization import canonical_stat_label


@dataclass(frozen=True)
class PlausibilityResult:
    valid: bool
    sport: str
    stat: str
    line: float | None
    minimum: float | None = None
    maximum: float | None = None
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "sport": self.sport,
            "stat": self.stat,
            "line": self.line,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "reason": self.reason,
        }


# These are deliberately broad market-line guardrails, not projections. They
# reject category mismatches without filtering ordinary alternate lines.
_SPORT_STAT_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "MLB": {
        "Hits": (0.5, 4.5),
        "Runs": (0.5, 3.5),
        "RBIs": (0.5, 5.5),
        "Hits + Runs + RBIs": (0.5, 12.5),
        "Home Runs": (0.5, 2.5),
        "Total Bases": (0.5, 8.5),
        "Singles": (0.5, 3.5),
        "Doubles": (0.5, 2.5),
        "Walks": (0.5, 4.5),
        "Strikeouts": (0.5, 16.5),
        "Pitcher Strikeouts": (0.5, 16.5),
        "Earned Runs": (0.5, 9.5),
        "Outs Recorded": (0.5, 30.5),
        "Hits Allowed": (0.5, 13.5),
        "Pitching Walks": (0.5, 7.5),
    },
    "NBA": {
        "Points": (0.5, 70.5),
        "Rebounds": (0.5, 32.5),
        "Assists": (0.5, 25.5),
        "Points + Rebounds + Assists": (0.5, 115.5),
        "Points + Rebounds": (0.5, 95.5),
        "Points + Assists": (0.5, 95.5),
        "Rebounds + Assists": (0.5, 55.5),
        "3-Pointers Made": (0.5, 15.5),
        "3-Pointers Attempted": (0.5, 30.5),
        "Field Goals Made": (0.5, 30.5),
        "Field Goals Attempted": (0.5, 50.5),
        "Free Throws Made": (0.5, 30.5),
        "Free Throws Attempted": (0.5, 35.5),
        "2-Pointers Made": (0.5, 25.5),
        "2-Pointers Attempted": (0.5, 40.5),
        "Offensive Rebounds": (0.5, 15.5),
        "Defensive Rebounds": (0.5, 25.5),
        "Blocks": (0.5, 9.5),
        "Steals": (0.5, 9.5),
        "Turnovers": (0.5, 12.5),
        "Steals + Blocks": (0.5, 15.5),
        "Double Doubles": (0.5, 1.5),
        "Triple Doubles": (0.5, 1.5),
    },
    "WNBA": {
        "Points": (0.5, 55.5),
        "Rebounds": (0.5, 25.5),
        "Assists": (0.5, 20.5),
        "Points + Rebounds + Assists": (0.5, 95.5),
        "Points + Rebounds": (0.5, 80.5),
        "Points + Assists": (0.5, 75.5),
        "Rebounds + Assists": (0.5, 45.5),
        "3-Pointers Made": (0.5, 12.5),
        "3-Pointers Attempted": (0.5, 25.5),
        "Field Goals Made": (0.5, 25.5),
        "Field Goals Attempted": (0.5, 40.5),
        "Free Throws Made": (0.5, 25.5),
        "Free Throws Attempted": (0.5, 30.5),
        "2-Pointers Made": (0.5, 22.5),
        "2-Pointers Attempted": (0.5, 35.5),
        "Offensive Rebounds": (0.5, 12.5),
        "Defensive Rebounds": (0.5, 20.5),
        "Blocks": (0.5, 8.5),
        "Steals": (0.5, 8.5),
        "Turnovers": (0.5, 10.5),
        "Steals + Blocks": (0.5, 12.5),
        "Double Doubles": (0.5, 1.5),
        "Triple Doubles": (0.5, 1.5),
    },
    "NFL": {
        "Passing Yards": (25.5, 525.5),
        "Passing TDs": (0.5, 7.5),
        "Passing Attempts": (5.5, 70.5),
        "Completions": (2.5, 55.5),
        "Interceptions": (0.5, 5.5),
        "Rushing Yards": (0.5, 275.5),
        "Rush Attempts": (0.5, 40.5),
        "Rushing TDs": (0.5, 4.5),
        "Receiving Yards": (0.5, 275.5),
        "Receptions": (0.5, 20.5),
        "Targets": (0.5, 25.5),
        "Receiving TDs": (0.5, 4.5),
        "Rush + Rec Yards": (0.5, 325.5),
        "Rush + Rec TDs": (0.5, 5.5),
        "Pass + Rush Yards": (25.5, 600.5),
        "Pass + Rush TDs": (0.5, 8.5),
        "Sacks": (0.5, 5.5),
        "Tackles": (0.5, 25.5),
        "Solo Tackles": (0.5, 20.5),
        "Assisted Tackles": (0.5, 15.5),
        "Extra Points Made": (0.5, 8.5),
        "Extra Points Attempted": (0.5, 8.5),
        "Field Goals Made": (0.5, 7.5),
        "Field Goals Attempted": (0.5, 8.5),
        "Longest Field Goal": (15.5, 75.5),
        "Kicking Points": (0.5, 25.5),
    },
    "NHL": {
        "Goals": (0.5, 3.5),
        "Assists": (0.5, 4.5),
        "Points": (0.5, 5.5),
        "Shots on Goal": (0.5, 12.5),
        "Blocked Shots": (0.5, 12.5),
        "Hits": (0.5, 15.5),
        "Saves": (5.5, 65.5),
        "Goalie Saves": (5.5, 65.5),
        "Goals Against": (0.5, 9.5),
        "Shots Against": (5.5, 70.5),
    },
}


def prop_line_plausibility(prop: object) -> PlausibilityResult:
    sport = str(_value(prop, "sport") or _value(prop, "league") or "").strip().upper()
    raw_stat = str(_value(prop, "stat") or "").strip()
    stat = canonical_stat_label(raw_stat)
    raw_line = _value(prop, "line")
    try:
        line = float(raw_line) if raw_line is not None else None
    except (TypeError, ValueError):
        line = None
    if line is None:
        return PlausibilityResult(False, sport, stat, None, reason="A numeric market line is required.")
    if line < 0:
        return PlausibilityResult(False, sport, stat, line, reason="Market lines cannot be negative.")

    range_sport = "NFL" if sport == "NCAAF" else sport
    bounds = _SPORT_STAT_RANGES.get(range_sport, {}).get(stat)
    if bounds is None:
        return PlausibilityResult(True, sport, stat, line)
    minimum, maximum = bounds
    if minimum <= line <= maximum:
        return PlausibilityResult(True, sport, stat, line, minimum, maximum)
    return PlausibilityResult(
        False,
        sport,
        stat,
        line,
        minimum,
        maximum,
        f"{sport} {stat} line {line:g} is outside the supported market range {minimum:g}-{maximum:g}.",
    )


def plausible_prop_line(prop: object) -> bool:
    return prop_line_plausibility(prop).valid


def _value(prop: object, key: str):
    if isinstance(prop, dict):
        return prop.get(key)
    value = getattr(prop, key, None)
    if key == "sport" and value is None:
        player = getattr(prop, "player", None)
        value = getattr(player, "sport", None)
    return getattr(value, "value", value)
