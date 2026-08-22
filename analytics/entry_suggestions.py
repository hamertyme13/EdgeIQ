from __future__ import annotations

import time
from dataclasses import dataclass, replace
from threading import Lock

from analytics.correlation import detect_correlations
from analytics.entry_recommendation import recommendation
from analytics.model_feedback import feedback_adjustment, settled_feedback_entries
from analytics.probabilistic_forecast import PropForecast, forecast_prop
from analytics.projection import auto_projection
from analytics.prop_metrics import calculate_confidence, calculate_directional_edge
from models.entry import Entry
from models.platform import Platform
from models.player import Player
from models.prop import Prop
from models.stat_type import StatType
from utils.entity_normalization import canonical_person_key
from utils.market_validation import is_supported_full_game_stat
from utils.stat_normalization import stat_type_from_text

_FORECAST_CACHE: dict[tuple, tuple[float, PropForecast]] = {}
_FORECAST_CACHE_LOCK = Lock()
_FORECAST_CACHE_TTL_SECONDS = 90.0


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
    diversify: bool = False,
    avoid_prop_keys: set[str] | None = None,
) -> list[SuggestedEntry]:
    if leg_count < 2:
        raise ValueError("Suggested entries need at least two legs.")

    recommendation_props = _prefilter_raw_markets(
        [prop for prop in raw_props if _recommendation_offer_allowed(prop, platform)],
        sport,
        limit=max(12, leg_count * 2),
    )
    forecast_cache: dict[tuple, PropForecast] = {}
    candidates = []
    for prop in recommendation_props:
        if prop.get("line") is None or (
            sport.upper() != "ALL SPORTS" and prop.get("league", "").upper() != sport.upper()
        ):
            continue
        candidates.extend(_props_from_feed(prop, platform, forecast_cache))

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
    selected_rows = (
        _diversified_scored_entries(scored, limit, avoid_prop_keys or set())
        if diversify
        else scored[:limit]
    )

    suggestions: list[SuggestedEntry] = []
    for rank, (score, entry, warnings) in enumerate(selected_rows, start=1):
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


def prop_exposure_key(prop: Prop) -> str:
    player = canonical_person_key(prop.player.name)
    stat = str(prop.stat.value or "").strip().lower().replace(",", "")
    direction = str(prop.direction or "Over").strip().lower()
    return f"{player}|{stat}|{direction}|{float(prop.line):.2f}"


def _diversified_scored_entries(
    scored: list[tuple[float, Entry, list[str]]],
    limit: int,
    avoid_prop_keys: set[str],
    quality_band: float = 12.0,
) -> list[tuple[float, Entry, list[str]]]:
    remaining = list(scored)
    selected: list[tuple[float, Entry, list[str]]] = []
    used_prop_counts: dict[str, int] = {}
    used_player_counts: dict[str, int] = {}

    while remaining and len(selected) < limit:
        best_score = remaining[0][0]
        comparable = [row for row in remaining if row[0] >= best_score - quality_band]

        def diversity_rank(row: tuple[float, Entry, list[str]]) -> tuple[int, int, int, float]:
            score, entry, _warnings = row
            keys = {prop_exposure_key(prop) for prop in entry.props}
            players = {canonical_person_key(prop.player.name) for prop in entry.props}
            return (
                len(keys & avoid_prop_keys),
                sum(used_prop_counts.get(key, 0) for key in keys),
                sum(used_player_counts.get(player, 0) for player in players),
                -score,
            )

        chosen = min(comparable, key=diversity_rank)
        selected.append(chosen)
        remaining.remove(chosen)
        for prop in chosen[1].props:
            key = prop_exposure_key(prop)
            player = canonical_person_key(prop.player.name)
            used_prop_counts[key] = used_prop_counts.get(key, 0) + 1
            used_player_counts[player] = used_player_counts.get(player, 0) + 1

    return selected


def _recommendation_offer_allowed(raw: dict, platform: Platform) -> bool:
    """Keep provider offers whose supported side can be modeled honestly."""
    return raw.get("line") is not None and is_supported_full_game_stat(raw.get("stat"))


def _prefilter_raw_markets(raw_props: list[dict], sport: str, limit: int = 16) -> list[dict]:
    """Bound expensive history forecasts while retaining enough markets for diverse cards.

    Each market can create both an over and under candidate. The caller scales
    this shortlist with the requested leg count so longer cards retain enough
    unique players without making small-card users wait on unused forecasts.
    """
    filtered = [
        prop for prop in raw_props
        if sport.upper() == "ALL SPORTS" or str(prop.get("league") or prop.get("sport") or "").upper() == sport.upper()
    ]
    filtered.sort(key=lambda prop: (
        int(str(prop.get("line_offer_type") or prop.get("odds_type") or "standard").lower() == "standard"),
        float(prop.get("source_score") or 0.0), int(prop.get("trending_count") or 0),
    ), reverse=True)
    selected, seen = [], set()
    player_counts: dict[str, int] = {}
    for prop in filtered:
        player = canonical_person_key(prop.get("player"))
        key = (player, str(prop.get("stat") or "").strip().lower(), str(prop.get("game") or "").strip().lower())
        if not player or key in seen or player_counts.get(player, 0) >= 8:
            continue
        seen.add(key)
        player_counts[player] = player_counts.get(player, 0) + 1
        selected.append(prop)
        if len(selected) >= limit:
            break
    return selected


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


def _props_from_feed(raw: dict, platform: Platform, forecast_cache: dict[tuple, PropForecast] | None = None) -> list[Prop]:
    line = float(raw.get("line") or 0.0)
    baseline_line = float(raw.get("baseline_line") or raw.get("standard_line") or line)
    trending_count = int(raw.get("trending_count") or 0)
    explicit_direction = _explicit_direction(raw.get("direction"))
    if platform == Platform.PRIZEPICKS and _is_demon_offer(raw):
        explicit_direction = "Over"
    projection_value = raw.get("projection")

    if projection_value not in (None, ""):
        projection = float(projection_value)
        direction = explicit_direction or _adjusted_offer_direction(raw, line, baseline_line) or ("Under" if projection < line else "Over")
        return [_prop_from_side(raw, platform, line, trending_count, direction, projection)]

    forecast_direction = explicit_direction or _adjusted_offer_direction(raw, line, baseline_line) or "Over"
    cache = forecast_cache if forecast_cache is not None else {}
    forecast_key = (
        canonical_person_key(raw.get("player")), str(raw.get("league") or "").upper(),
        str(raw.get("stat") or "").lower(), baseline_line, forecast_direction,
        str(raw.get("game") or ""), str(raw.get("team") or ""),
    )
    forecast = cache.get(forecast_key)
    if forecast is None:
        forecast = _cached_forecast(raw, baseline_line, forecast_direction, forecast_key)
        cache[forecast_key] = forecast
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


def _cached_forecast(raw: dict, baseline_line: float, direction: str, key: tuple) -> PropForecast:
    now = time.monotonic()
    with _FORECAST_CACHE_LOCK:
        cached = _FORECAST_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
    forecast = forecast_prop(
        raw.get("player", ""), raw.get("league", ""), raw.get("stat", ""),
        baseline_line, direction, game_time=raw.get("game_time", ""),
        team=raw.get("team", ""), game=raw.get("game", ""),
    )
    with _FORECAST_CACHE_LOCK:
        _FORECAST_CACHE[key] = (now + _FORECAST_CACHE_TTL_SECONDS, forecast)
        if len(_FORECAST_CACHE) > 2000:
            expired = [cache_key for cache_key, value in _FORECAST_CACHE.items() if value[0] <= now]
            for cache_key in expired or list(_FORECAST_CACHE)[:500]:
                _FORECAST_CACHE.pop(cache_key, None)
    return forecast


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
        provider_projection_id=str(raw.get("projection_id") or raw.get("provider_projection_id") or ""),
        provider_offer_verified=bool(raw.get("projection_id") or raw.get("provider_projection_id")),
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


def _is_demon_offer(raw: dict) -> bool:
    offer_type = str(raw.get("line_offer_type") or raw.get("odds_type") or "").strip().lower()
    return bool(raw.get("is_premium_line")) or offer_type == "demon"


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
