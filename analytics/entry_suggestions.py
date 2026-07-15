from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from analytics.correlation import detect_correlations
from analytics.entry_recommendation import recommendation
from analytics.model_feedback import feedback_adjustment
from analytics.prop_metrics import calculate_confidence, calculate_edge
from analytics.projection import auto_projection
from models.entry import Entry
from models.platform import Platform
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType
from utils.stat_normalization import stat_type_from_text


@dataclass
class SuggestedEntry:
    rank: int
    entry: Entry
    score: float
    grade: str
    action: str
    warnings: list[str]


def suggest_entries(
    raw_props: list[dict],
    sport: str,
    platform: Platform,
    limit: int = 5,
    leg_count: int = 2,
    min_confidence: float = 0.0,
    min_edge: float = -999.0,
    max_same_team: int | None = None,
    exclude_correlated: bool = False,
    apply_feedback: bool = False,
) -> list[SuggestedEntry]:
    if leg_count < 2:
        raise ValueError("Suggested entries need at least two legs.")

    candidates = [
        candidate
        for prop in raw_props
        if prop.get("line") is not None and prop.get("league", "").upper() == sport.upper()
        for candidate in _props_from_feed(prop, platform)
    ]

    candidates.sort(key=_candidate_sort_key, reverse=True)
    candidates = _unique_players(candidates)[:16]

    scored: list[tuple[float, Entry, list[str]]] = []
    for props in itertools.combinations(candidates, leg_count):
        entry = Entry(platform=platform, props=list(props))
        warnings = detect_correlations(entry)
        if exclude_correlated and warnings:
            continue
        if max_same_team is not None and _max_team_count(entry) > max_same_team:
            continue
        if entry.average_confidence < min_confidence or entry.average_edge < min_edge:
            continue
        if apply_feedback:
            for prop in entry.props:
                prop.confidence = max(0.0, min(100.0, prop.confidence + feedback_adjustment(prop.confidence)))
        score = _score_entry(entry, warnings)
        scored.append((score, entry, warnings))

    scored.sort(key=lambda item: item[0], reverse=True)

    suggestions: list[SuggestedEntry] = []
    for rank, (score, entry, warnings) in enumerate(scored[:limit], start=1):
        result = recommendation(entry)
        suggestions.append(
            SuggestedEntry(
                rank=rank,
                entry=entry,
                score=round(score, 1),
                grade=result["grade"],
                action=result["action"],
                warnings=warnings,
            )
        )

    return suggestions


def _score_entry(entry: Entry, warnings: list[str]) -> float:
    trend_score = sum(math.log10(max(prop.trending_count, 1)) for prop in entry.props)
    warning_penalty = len(warnings) * 8
    same_team_penalty = 6 if len({prop.player.team for prop in entry.props}) < len(entry.props) else 0
    return (
        entry.average_confidence
        + entry.average_edge * 10
        + trend_score
        - warning_penalty
        - same_team_penalty
    )


def _max_team_count(entry: Entry) -> int:
    counts: dict[str, int] = {}
    for prop in entry.props:
        team = prop.player.team or prop.player.name
        counts[team] = counts.get(team, 0) + 1
    return max(counts.values(), default=0)


def _candidate_sort_key(prop: Prop) -> tuple[float, float, int, int]:
    side_bonus = 1 if prop.direction == _preferred_tie_side(prop) else 0
    return (prop.confidence, prop.edge, prop.trending_count, side_bonus)


def _preferred_tie_side(prop: Prop) -> str:
    key = f"{prop.player.name}|{prop.stat.value}".lower()
    return "Under" if sum(ord(char) for char in key) % 2 else "Over"


def _props_from_feed(raw: dict, platform: Platform) -> list[Prop]:
    line = float(raw.get("line") or 0.0)
    trending_count = int(raw.get("trending_count") or 0)
    explicit_direction = _explicit_direction(raw.get("direction"))
    projection_value = raw.get("projection")

    if projection_value not in (None, ""):
        projection = float(projection_value)
        direction = explicit_direction or ("Under" if projection < line else "Over")
        return [_prop_from_side(raw, platform, line, trending_count, direction, projection)]

    if explicit_direction:
        projection = _side_projection(line, trending_count, explicit_direction)
        return [_prop_from_side(raw, platform, line, trending_count, explicit_direction, projection)]

    return [
        _prop_from_side(raw, platform, line, trending_count, "Over", _side_projection(line, trending_count, "Over")),
        _prop_from_side(raw, platform, line, trending_count, "Under", _side_projection(line, trending_count, "Under")),
    ]


def _prop_from_side(raw: dict, platform: Platform, line: float, trending_count: int, direction: str, projection: float) -> Prop:
    edge = _directional_edge(line, projection, direction)
    hit_rate = raw.get("hit_rate") or {}

    return Prop(
        player=Player(
            name=raw.get("player", "Player"),
            team=raw.get("team", ""),
            sport=raw.get("league", ""),
        ),
        stat=_stat_from_text(raw.get("stat", "")),
        line=line,
        projection=projection,
        edge=edge,
        confidence=calculate_confidence(edge),
        direction=direction,
        platform=platform,
        game=raw.get("game", ""),
        game_time=raw.get("game_time", ""),
        season_type=raw.get("season_type", ""),
        needs_projection=False,
        auto_projected=raw.get("projection") in (None, ""),
        trending_count=trending_count,
        projection_source=raw.get("projection_source", "confirmed_provider" if raw.get("confirmation") else "line_model"),
        espn_hit_rate=hit_rate.get("estimated_hit_rate"),
        espn_sample_size=int(hit_rate.get("sample_size") or raw.get("espn_sample_size") or 0),
        espn_note=hit_rate.get("note", ""),
        source_signals=raw.get("source_signals") or raw.get("confirmation_signals") or [],
        source_score=float(raw.get("source_score") or 0.0),
    )


def _side_projection(line: float, trending_count: int, direction: str) -> float:
    over_projection = auto_projection(line, trending_count)
    adjustment = max(0.2, abs(over_projection - line))
    if direction == "Under":
        return round(max(0.0, line - adjustment), 1)
    return over_projection


def _directional_edge(line: float, projection: float, direction: str) -> float:
    if direction == "Under":
        return line - projection
    return calculate_edge(line, projection)


def _explicit_direction(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"under", "u", "less", "lower"}:
        return "Under"
    if text in {"over", "o", "more", "higher"}:
        return "Over"
    return None


def _unique_players(props: list[Prop]) -> list[Prop]:
    unique: list[Prop] = []
    seen: set[str] = set()

    for prop in props:
        key = prop.player.name.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(prop)

    return unique


def _stat_from_text(value: str) -> StatType:
    return stat_type_from_text(value)
