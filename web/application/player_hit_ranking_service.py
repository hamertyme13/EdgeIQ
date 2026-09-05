from __future__ import annotations

from collections.abc import Callable
from typing import Any

from analytics.probabilistic_forecast import forecast_prop
from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.stat_normalization import canonical_stat_label


def player_stat_hit_leaderboard(
    player: str,
    player_props: list[dict],
    sport: str | None,
    history_loader: Callable[..., list[dict]] = FinalStatsRepository.history,
) -> list[dict]:
    by_stat: dict[str, list[dict]] = {}
    for prop in _prefer_standard_offers(player_props):
        if prop.get("line") is not None and prop.get("stat"):
            by_stat.setdefault(canonical_stat_label(prop["stat"]), []).append(prop)
    rows: list[dict[str, Any]] = []
    for stat_label, offers in by_stat.items():
        offer = max(offers, key=lambda row: (
            int(str(row.get("line_offer_type") or row.get("odds_type") or "standard").lower() == "standard"),
            int(row.get("trending_count") or 0),
        ))
        line, team = float(offer.get("line") or 0.0), str(offer.get("team") or "")
        history = history_loader(player, stat_label, sport=sport, limit=120, team=team)
        history = [row for row in history if str(row.get("status") or "played").lower() == "played" and row.get("actual") is not None]
        if len(history) < 3:
            continue
        forecast = forecast_prop(
            player, sport or str(offer.get("league") or ""), stat_label, line, "Over",
            history=history, game_time=offer.get("game_time"), team=team, game=str(offer.get("game") or ""),
        )
        direction = "Under" if forecast.projection < line else "Over"
        decisions = [float(row["actual"]) for row in history if float(row["actual"]) != line]
        if not decisions:
            continue
        recent = decisions[:10]
        rows.append({
            "stat": stat_label, "direction": direction, "line": line,
            "platform": str(offer.get("platform") or ""), "projection": forecast.projection,
            "season_hit_rate": _rate(decisions, line, direction),
            "recent_10_hit_rate": _rate(recent, line, direction),
            "season_average": round(sum(float(row["actual"]) for row in history) / len(history), 2),
            "sample_size": len(history),
            "sample_strength": "Strong" if len(history) >= 25 else "Developing" if len(history) >= 10 else "Thin",
            "uncertainty": {
                "level": forecast.distribution.get("uncertainty_level", "Unknown"),
                "percentile_25": forecast.distribution.get("percentile_25"),
                "percentile_75": forecast.distribution.get("percentile_75"),
                "floor": forecast.distribution.get("floor"), "ceiling": forecast.distribution.get("ceiling"),
            },
            "note": _sample_note(len(history)),
        })
    rows.sort(key=lambda row: (
        min(int(row["sample_size"]), 25) / 25.0 * float(row["season_hit_rate"]),
        float(row["recent_10_hit_rate"]), int(row["sample_size"]),
    ), reverse=True)
    return rows[:8]


def _prefer_standard_offers(props: list[dict]) -> list[dict]:
    standard_keys = {
        (str(prop.get("platform") or ""), canonical_stat_label(prop.get("stat")))
        for prop in props if str(prop.get("line_offer_type") or prop.get("odds_type") or "standard").lower() == "standard"
    }
    return [prop for prop in props if (
        (str(prop.get("platform") or ""), canonical_stat_label(prop.get("stat"))) not in standard_keys
        or str(prop.get("line_offer_type") or prop.get("odds_type") or "standard").lower() == "standard"
    )]


def _rate(values: list[float], line: float, direction: str) -> float:
    hits = sum(value < line if direction == "Under" else value > line for value in values)
    return round(hits / len(values) * 100.0, 1)


def _sample_note(sample_size: int) -> str:
    if sample_size >= 25:
        return "Strong season sample at the current standard line."
    if sample_size >= 10:
        return "Useful early signal, but the season sample is still developing."
    return "Thin sample; use this for research or paper tracking only."
