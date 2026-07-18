from analytics.confidence import confidence
from models.stat_type import StatType
from utils.stat_normalization import stat_type_from_text


def calculate_edge(
    line: float,
    projection: float
) -> float:
    """Calculate the betting edge."""

    return projection - line


def calculate_confidence(
    edge: float,
    stat: object | None = None,
    sport: object | None = None,
) -> float:
    """Calculate confidence from the edge, adjusted for market volatility."""

    if stat is None and sport is None:
        return confidence(edge)

    return confidence(edge * _market_edge_weight(stat, sport))


def _market_edge_weight(stat: object | None, sport: object | None) -> float:
    stat_type = stat_type_from_text(stat, default=StatType.POINTS) if stat is not None else None
    sport_key = str(sport or "").strip().upper()
    weight = 1.0

    if stat_type in {
        StatType.PRA,
        StatType.POINTS_REBOUNDS,
        StatType.POINTS_ASSISTS,
        StatType.REBOUNDS_ASSISTS,
        StatType.FANTASY_SCORE,
    }:
        weight *= 0.72
    elif stat_type in {
        StatType.POINTS,
        StatType.PASSING_YARDS,
        StatType.RUSHING_YARDS,
        StatType.RECEIVING_YARDS,
        StatType.HITS_RUNS_RBIS,
        StatType.TOTAL_BASES,
    }:
        weight *= 0.88
    elif stat_type in {
        StatType.ASSISTS,
        StatType.REBOUNDS,
        StatType.RECEPTIONS,
        StatType.STRIKEOUTS,
        StatType.PITCHER_STRIKEOUTS,
        StatType.SHOTS_ON_GOAL,
        StatType.SAVES,
    }:
        weight *= 1.05
    elif stat_type in {
        StatType.BLOCKS,
        StatType.STEALS,
        StatType.HOME_RUNS,
        StatType.RBIS,
        StatType.GOALS,
        StatType.DOUBLE_DOUBLES,
    }:
        weight *= 0.58

    if sport_key in {"MLB", "NHL", "MLS", "EPL", "UCL", "TENNIS", "PGA", "MMA", "NASCAR"}:
        weight *= 0.9
    elif sport_key in {"NBA", "WNBA", "NCAAM", "NCAAW"}:
        weight *= 1.0
    elif sport_key in {"NFL", "NCAAF"}:
        weight *= 0.84

    return max(0.45, min(1.18, weight))
