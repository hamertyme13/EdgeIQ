from __future__ import annotations

from dataclasses import dataclass, replace

from analytics.correlation import detect_correlations
from analytics.entry_recommendation import recommendation
from analytics.model_feedback import feedback_adjustment, settled_feedback_entries
from analytics.prop_metrics import calculate_confidence, calculate_directional_edge
from analytics.projection import auto_projection
from analytics.probabilistic_forecast import forecast_prop
from models.entry import Entry
from models.platform import Platform
from models.player import Player
from models.prop import Prop
from utils.entity_normalization import canonical_person_key
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
        if prop.get("line") is not None
        and (sport.upper() == "ALL SPORTS" or prop.get("league", "").upper() == sport.upper())
        for candidate in _props_from_feed(prop, platform)
    ]

    candidates.sort(key=_candidate_sort_key, reverse=True)
    candidates = _top_markets_per_player(candidates, per_player=2, limit=48)
    adjusted_candidates: dict[int, Prop] = {}
    if apply_feedback:
        feedback_entries = settled_feedback_entries()
        for prop in candidates:
            adjustment = feedback_adjustment(prop.confidence, prop, feedback_entries)
            adjusted_candidates[id(prop)] = replace(
                prop,
                confidence_adjustment=adjustment,
                confidence=max(0.0, min(100.0, prop.confidence + adjustment)),
            )

    scored: list[tuple[float, Entry, list[str]]] = []
    for props in _beam_combinations(candidates, leg_count):
        if _has_duplicate_players(props):
            continue
        raw_entry = Entry(platform=platform, props=list(props))
        warnings = detect_correlations(raw_entry)
        if exclude_correlated and warnings:
            continue
        if max_same_team is not None and _max_team_count(raw_entry) > max_same_team:
            continue
        if raw_entry.average_confidence < min_confidence or raw_entry.average_edge < min_edge:
            continue
        entry = Entry(
            platform=platform,
            props=[adjusted_candidates[id(prop)] for prop in props],
        ) if apply_feedback else raw_entry
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
    warning_penalty = len(warnings) * 8
    same_team_penalty = 6 if len({prop.player.team for prop in entry.props}) < len(entry.props) else 0
    unproven_penalty = sum(8.0 for prop in entry.props if not prop.forecast_paid_eligible)
    model_bonus = sum(3.0 for prop in entry.props if prop.forecast_paid_eligible)
    adjusted_line_bonus = sum(3.0 for prop in entry.props if getattr(prop, "is_discounted_line", False))
    premium_line_penalty = sum(2.0 for prop in entry.props if getattr(prop, "is_premium_line", False))
    return (
        entry.average_confidence
        + entry.average_edge * 10
        + model_bonus
        + adjusted_line_bonus
        - warning_penalty
        - same_team_penalty
        - unproven_penalty
        - premium_line_penalty
    )


def _max_team_count(entry: Entry) -> int:
    counts: dict[str, int] = {}
    for prop in entry.props:
        team = prop.player.team or prop.player.name
        counts[team] = counts.get(team, 0) + 1
    return max(counts.values(), default=0)


def _candidate_sort_key(prop: Prop) -> tuple[int, float, float, float, str]:
    sample_size = float((prop.forecast_snapshot or {}).get("effective_sample_size") or 0.0)
    return (
        int(prop.forecast_paid_eligible),
        prop.confidence,
        prop.edge,
        sample_size,
        prop.direction,
    )


def _beam_combinations(candidates: list[Prop], leg_count: int, beam_width: int = 1500):
    states: list[tuple[tuple[int, ...], tuple[Prop, ...]]] = [((), ())]
    for _ in range(leg_count):
        expanded: list[tuple[float, tuple[int, ...], tuple[Prop, ...]]] = []
        for indices, props in states:
            start = indices[-1] + 1 if indices else 0
            names = {canonical_person_key(prop.player.name) for prop in props}
            for index in range(start, len(candidates)):
                candidate = candidates[index]
                if canonical_person_key(candidate.player.name) in names:
                    continue
                next_props = props + (candidate,)
                partial_score = (
                    sum(prop.confidence for prop in next_props) / len(next_props)
                    + sum(prop.edge for prop in next_props) * 4.0
                    + sum(3.0 for prop in next_props if prop.forecast_paid_eligible)
                )
                expanded.append((partial_score, indices + (index,), next_props))
        expanded.sort(key=lambda row: row[0], reverse=True)
        states = [(indices, props) for _, indices, props in expanded[:beam_width]]
        if not states:
            break
    return [props for _, props in states if len(props) == leg_count]


def _props_from_feed(raw: dict, platform: Platform) -> list[Prop]:
    line = float(raw.get("line") or 0.0)
    baseline_line = float(raw.get("baseline_line") or raw.get("standard_line") or line)
    trending_count = int(raw.get("trending_count") or 0)
    explicit_direction = _explicit_direction(raw.get("direction"))
    projection_value = raw.get("projection")

    if projection_value not in (None, ""):
        projection = float(projection_value)
        direction = explicit_direction or _adjusted_offer_direction(raw, line, baseline_line) or ("Under" if projection < line else "Over")
        return [_prop_from_side(raw, platform, line, trending_count, direction, projection)]

    forecast_direction = explicit_direction or _adjusted_offer_direction(raw, line, baseline_line) or "Over"
    forecast = forecast_prop(
        raw.get("player", ""),
        raw.get("league", ""),
        raw.get("stat", ""),
        baseline_line,
        forecast_direction,
        game_time=raw.get("game_time", ""),
        team=raw.get("team", ""),
        game=raw.get("game", ""),
    )
    raw = {
        **raw,
        "forecast_probability": forecast.probability,
        "forecast_direction": forecast_direction,
        "forecast_snapshot": forecast.snapshot(),
        "projection_source": forecast.source,
        "auto_projected": True,
    }

    if explicit_direction:
        return [_prop_from_side(raw, platform, line, trending_count, explicit_direction, forecast.projection)]

    adjusted_direction = _adjusted_offer_direction(raw, line, baseline_line)
    if adjusted_direction:
        return [_prop_from_side(raw, platform, line, trending_count, adjusted_direction, forecast.projection)]

    return [
        _prop_from_side(raw, platform, line, trending_count, "Over", forecast.projection),
        _prop_from_side(raw, platform, line, trending_count, "Under", forecast.projection),
    ]


def _prop_from_side(raw: dict, platform: Platform, line: float, trending_count: int, direction: str, projection: float) -> Prop:
    edge = _directional_edge(line, projection, direction)
    hit_rate = raw.get("hit_rate") or {}
    auto_projected = bool(raw.get("auto_projected")) if "auto_projected" in raw else raw.get("projection") in (None, "")
    projection_source = raw.get(
        "projection_source",
        "confirmed_provider" if raw.get("confirmation") or not auto_projected else "line_model",
    )

    confidence = calculate_confidence(edge, raw.get("stat", ""), raw.get("league", ""))
    forecast_probability = raw.get("forecast_probability")
    if forecast_probability is not None:
        confidence = float(forecast_probability)
        if direction != raw.get("forecast_direction"):
            confidence = 100.0 - confidence
    forecast_snapshot = raw.get("forecast_snapshot") or {}
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
        confidence=confidence,
        direction=direction,
        platform=platform,
        game=raw.get("game", ""),
        game_time=raw.get("game_time", ""),
        position=raw.get("position", ""),
        season_type=raw.get("season_type", ""),
        needs_projection=False,
        auto_projected=auto_projected,
        trending_count=trending_count,
        projection_source=projection_source,
        baseline_line=float(raw.get("baseline_line") or raw.get("standard_line") or line),
        standard_line=raw.get("standard_line"),
        line_offer_type=str(raw.get("line_offer_type") or raw.get("odds_type") or "standard"),
        adjusted_line=bool(raw.get("adjusted_line") or raw.get("adjusted_odds")),
        is_discounted_line=bool(raw.get("is_discounted_line")),
        is_premium_line=bool(raw.get("is_premium_line")),
        line_discount=float(raw.get("line_discount") or 0.0),
        espn_hit_rate=hit_rate.get("estimated_hit_rate"),
        espn_sample_size=int(hit_rate.get("sample_size") or raw.get("espn_sample_size") or 0),
        espn_note=hit_rate.get("note", ""),
        source_signals=raw.get("source_signals") or raw.get("confirmation_signals") or [],
        source_score=float(raw.get("source_score") or 0.0),
        player_identity_id=raw.get("player_identity_id"),
        player_provider=str(raw.get("player_provider") or raw.get("platform") or platform.value),
        provider_player_id=str(raw.get("provider_player_id") or raw.get("player_id") or ""),
        model_version=str(forecast_snapshot.get("model_version") or ""),
        feature_as_of=str(forecast_snapshot.get("feature_as_of") or ""),
        forecast_snapshot=forecast_snapshot,
        forecast_paid_eligible=bool(forecast_snapshot.get("paid_eligible")),
    )


def _side_projection(line: float, trending_count: int, direction: str) -> float:
    over_projection = auto_projection(line, trending_count)
    adjustment = max(0.2, abs(over_projection - line))
    if direction == "Under":
        return round(max(0.0, line - adjustment), 1)
    return over_projection


def _directional_edge(line: float, projection: float, direction: str) -> float:
    return calculate_directional_edge(line, projection, direction)


def _explicit_direction(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"under", "u", "less", "lower"}:
        return "Under"
    if text in {"over", "o", "more", "higher"}:
        return "Over"
    return None


def _adjusted_offer_direction(raw: dict, line: float, baseline_line: float) -> str | None:
    if not (raw.get("adjusted_line") or raw.get("adjusted_odds") or raw.get("line_offer_type") or raw.get("odds_type")):
        return None
    delta = line - baseline_line
    if abs(delta) < 0.01:
        return None
    if raw.get("is_discounted_line") or str(raw.get("line_offer_type") or raw.get("odds_type") or "").lower() == "goblin":
        return "Over" if delta < 0 else "Under"
    if raw.get("is_premium_line") or str(raw.get("line_offer_type") or raw.get("odds_type") or "").lower() == "demon":
        return "Over" if delta > 0 else "Under"
    return None


def _top_markets_per_player(props: list[Prop], per_player: int = 2, limit: int = 24) -> list[Prop]:
    selected: list[Prop] = []
    counts: dict[str, int] = {}

    for prop in props:
        key = canonical_person_key(prop.player.name)
        if not key or counts.get(key, 0) >= per_player:
            continue
        counts[key] = counts.get(key, 0) + 1
        selected.append(prop)
        if len(selected) >= limit:
            break

    return selected


def _has_duplicate_players(props: tuple[Prop, ...]) -> bool:
    names = [canonical_person_key(prop.player.name) for prop in props]
    return len(names) != len(set(names))


def _stat_from_text(value: str) -> StatType:
    return stat_type_from_text(value)
