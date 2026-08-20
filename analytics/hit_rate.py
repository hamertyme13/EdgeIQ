from __future__ import annotations

from dataclasses import dataclass

from analytics.projection import auto_projection
from analytics.prop_metrics import calculate_directional_edge
from repository.repositories.final_stats_repository import FinalStatsRepository


@dataclass
class HitRateSummary:
    player: str
    stat: str
    line: float
    projection: float
    edge: float
    estimated_hit_rate: float
    last_5: float
    last_10: float
    season: float
    source: str
    sample_size: int
    note: str


def estimate_hit_rate(
    player: str,
    stat: str,
    line: float,
    projection: float | None = None,
    trending_count: int = 0,
    sport: str | None = None,
    direction: str = "Over",
    team: str = "",
) -> HitRateSummary:
    resolved_projection = projection if projection is not None else auto_projection(line, trending_count)
    edge = calculate_directional_edge(line, resolved_projection, direction)
    history = FinalStatsRepository.history(player, stat, sport=sport, limit=100, team=team)
    if history:
        return _from_history(player, stat, line, resolved_projection, edge, history, direction)

    base = _rate_from_edge(edge)

    return HitRateSummary(
        player=player,
        stat=stat,
        line=line,
        projection=round(resolved_projection, 2),
        edge=round(edge, 2),
        estimated_hit_rate=base,
        last_5=max(0.0, min(100.0, base + _trend_adjustment(trending_count, 1.5))),
        last_10=max(0.0, min(100.0, base + _trend_adjustment(trending_count, 0.8))),
        season=base,
        source="projection_model",
        sample_size=0,
        note="Estimated from projection edge. Connect final stat history for actual last-5/last-10/season hit rates.",
    )


def _from_history(
    player: str,
    stat: str,
    line: float,
    projection: float,
    edge: float,
    history: list[dict],
    direction: str,
) -> HitRateSummary:
    played_history = _played_rows(history)
    return HitRateSummary(
        player=player,
        stat=stat,
        line=line,
        projection=round(projection, 2),
        edge=round(edge, 2),
        estimated_hit_rate=_hit_rate(played_history, line, direction),
        last_5=_hit_rate(played_history[:5], line, direction),
        last_10=_hit_rate(played_history[:10], line, direction),
        season=_hit_rate(played_history, line, direction),
        source="final_stats",
        sample_size=len(played_history),
        note=f"Calculated from {len(played_history)} played final stat rows.",
    )


def _hit_rate(rows: list[dict], line: float, direction: str = "Over") -> float:
    if not rows:
        return 0.0
    if str(direction).lower() == "under":
        hits = sum(1 for row in rows if float(row["actual"]) < line)
    else:
        hits = sum(1 for row in rows if float(row["actual"]) > line)
    return round(hits / len(rows) * 100, 1)


def _played_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("status", "played") != "dnp"]


def _rate_from_edge(edge: float) -> float:
    return round(max(5.0, min(95.0, 50.0 + edge * 8.0)), 1)


def _trend_adjustment(trending_count: int, scale: float) -> float:
    if trending_count >= 10000:
        return scale
    if trending_count >= 1000:
        return scale / 2
    return 0.0
