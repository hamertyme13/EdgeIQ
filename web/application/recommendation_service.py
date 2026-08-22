from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from copy import deepcopy
from threading import Lock

from utils.entity_normalization import canonical_person_key


class RecommendationRequestError(ValueError):
    pass


_ENTRY_GENERATOR_CACHE: dict[tuple, tuple[float, dict]] = {}
_ENTRY_GENERATOR_LOCK = Lock()
_ENTRY_GENERATOR_TTL_SECONDS = 45.0


def top_props_payload(
    platform: str,
    sport: str,
    limit: int,
    *,
    fetch_props: Callable[[str, str | None], list[dict]],
    top_by_sport: Callable[[list[dict], int, str | None], list[dict]],
) -> dict:
    sport_filter = _sport_filter(sport)
    props = fetch_props(platform, sport_filter)
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    return {
        "props": top_by_sport(props, limit, sport_filter),
        "platform": platform,
        "sport": sport,
        "per_sport_limit": limit,
        "end_to_end_only": True,
        "settlement_provider": "ESPN official box score",
    }


def trending_props_payload(
    platform: str,
    sport: str,
    limit: int,
    *,
    fetch_props: Callable[[str, str | None], list[dict]],
    analyze_prop: Callable[[dict], dict],
    end_to_end_eligibility: Callable[[dict], dict],
) -> dict:
    """Return a small, fully analyzed market-interest shortlist."""
    sport_filter = _sport_filter(sport)
    props = fetch_props(platform, sport_filter)
    requested_limit = max(1, min(int(limit), 15))
    candidate_limit = max(30, requested_limit * 2)
    eligible: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    excluded = 0
    for raw in props:
        offer_type = str(raw.get("line_offer_type") or raw.get("odds_type") or "standard").lower()
        if str(raw.get("platform") or platform).strip().lower() == "prizepicks" and (
            raw.get("is_premium_line") or offer_type == "demon"
        ):
            raw = {**raw, "direction": "Over", "allowed_directions": ["Over"]}
        eligibility = end_to_end_eligibility(raw)
        if not eligibility.get("eligible"):
            excluded += 1
            continue
        key = (
            canonical_person_key(raw.get("player")),
            str(raw.get("stat") or "").strip().lower(),
            str(raw.get("game") or "").strip().lower(),
            str(raw.get("platform") or platform).strip().lower(),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        eligible.append(raw)

    eligible.sort(key=_trending_prefilter_key, reverse=True)
    analyzed_rows: list[dict] = []
    for raw in eligible[:candidate_limit]:
        analyzed = analyze_prop(raw)
        confidence = float(analyzed.get("confidence") or 0.0)
        quality_score = float((analyzed.get("data_quality") or {}).get("score") or 0.0)
        history = analyzed.get("hit_rate") or {}
        history_sample = min(20, int(history.get("sample_size") or 0))
        history_score = min(100.0, history_sample * 5.0)
        forecast_score = 100.0 if analyzed.get("forecast_paid_eligible") else 40.0
        activity_score = min(100.0, max(0.0, float(raw.get("trending_count") or 0)) / 1000.0)
        grade_score = (
            confidence * 0.45
            + quality_score * 0.30
            + history_score * 0.12
            + forecast_score * 0.08
            + activity_score * 0.05
        )
        if not analyzed.get("forecast_paid_eligible"):
            grade_score = min(grade_score, 69.9)
        grade = "A" if grade_score >= 80 else "B" if grade_score >= 70 else "C" if grade_score >= 58 else "D"
        analyzed_rows.append({
            **raw,
            "direction": analyzed.get("direction") or raw.get("direction") or "Over",
            "projection": analyzed.get("projection"),
            "confidence": round(confidence, 1),
            "grade": grade,
            "grade_score": round(grade_score, 1),
            "data_quality": analyzed.get("data_quality") or {},
            "data_strength": analyzed.get("data_strength") or [],
            "history_sample": history_sample,
            "forecast_paid_eligible": bool(analyzed.get("forecast_paid_eligible")),
            "end_to_end_confirmed": True,
            "settlement_provider": eligibility.get("provider") or "ESPN official box score",
        })

    analyzed_rows.sort(
        key=lambda row: (
            float(row.get("grade_score") or 0.0),
            float(row.get("confidence") or 0.0),
            float((row.get("data_quality") or {}).get("score") or 0.0),
            int(row.get("trending_count") or 0),
        ),
        reverse=True,
    )
    selected = analyzed_rows[:requested_limit]
    for rank, row in enumerate(selected, start=1):
        row["rank"] = rank
    return {
        "props": selected,
        "platform": platform,
        "sport": sport,
        "count": len(selected),
        "evaluated_count": min(len(eligible), candidate_limit),
        "eligible_count": len(eligible),
        "excluded": excluded,
        "mode": "graded_shortlist",
        "note": f"Top {len(selected)} graded props from {min(len(eligible), candidate_limit)} fully analyzed candidates. Verify live lines before entry.",
    }


def _trending_prefilter_key(prop: dict) -> tuple[int, int, float, int]:
    return (
        int(prop.get("projection") not in (None, "")),
        int(bool(prop.get("game_time"))),
        float(prop.get("source_score") or 0.0),
        int(prop.get("trending_count") or 0),
    )


def dashboard_parlay_payload(
    platform: str,
    sport: str,
    *,
    recommended_parlay: Callable[[str, str | None], object | None],
    serialize_suggestion: Callable[[object], dict],
) -> dict:
    suggestion = recommended_parlay(platform, _sport_filter(sport))
    return {
        "suggestion": serialize_suggestion(suggestion) if suggestion else None,
        "platform": platform,
        "sport": sport,
    }


def cached_command_center_payload(
    platform: str,
    sport: str,
    refresh: bool,
    *,
    cache: dict,
    lock: AbstractContextManager,
    ttl_seconds: float,
    canonical_platform: Callable[[str], str],
    selected_platforms: Callable[[str], list[str]],
    fetcher_token: Callable[[str], object],
    fetch_props_token: object,
    payload_token: object,
    build_payload: Callable[[str, str | None], dict],
) -> dict:
    sport_filter = _sport_filter(sport)
    cache_key = (
        canonical_platform(platform),
        sport_filter or "ALL",
        fetch_props_token,
        payload_token,
        tuple((canonical_platform(name), fetcher_token(name)) for name in selected_platforms(platform)),
    )
    now = time.monotonic()
    with lock:
        cached = cache.get(cache_key)
        if not refresh and cached and cached[0] > now:
            return cached[1]
        payload = build_payload(platform, sport_filter)
        cache[cache_key] = (now + ttl_seconds, payload)
        return payload


def entry_suggestions_payload(
    sport: str,
    platform: str,
    leg_count: int,
    *,
    canonical_platform: Callable[[str], str],
    entry_platforms: set[str],
    cached_briefing: Callable[[str, str | None], dict],
    fetch_props: Callable[[str, str | None], list[dict]],
    props_by_platform: Callable[[str, list[dict]], list[tuple]],
    mixed_risk: Callable[[list[dict], str, object], list],
    suggest: Callable[..., list],
    serialize_suggestion: Callable[[object], dict],
    avoid_prop_keys: set[str] | None = None,
) -> dict:
    started = time.perf_counter()
    sport_filter = _sport_filter(sport)
    entry_platform = canonical_platform(platform)
    if entry_platform not in entry_platforms and entry_platform != "Both":
        entry_platform = "PrizePicks"
    maximum_legs = _maximum_legs(entry_platform)
    if leg_count < 2 or leg_count > maximum_legs:
        raise RecommendationRequestError(
            f"{entry_platform} entries support between 2 and {maximum_legs} legs."
        )
    raw_props = fetch_props(entry_platform, sport_filter)
    cache_key = (
        entry_platform, sport_filter or "ALL", int(leg_count), tuple(sorted(avoid_prop_keys or set())), id(suggest),
        tuple(
            (str(prop.get("platform") or ""), str(prop.get("player") or ""), str(prop.get("stat") or ""),
             float(prop.get("line") or 0.0), str(prop.get("direction") or ""))
            for prop in raw_props[:150]
        ),
    )
    now = time.monotonic()
    with _ENTRY_GENERATOR_LOCK:
        cached = _ENTRY_GENERATOR_CACHE.get(cache_key)
        if cached and cached[0] > now:
            payload = deepcopy(cached[1])
            payload["performance"] = {"cache_hit": True, "generation_ms": round((time.perf_counter() - started) * 1000.0, 1)}
            return payload
    platform_pairs = props_by_platform(entry_platform, raw_props)
    if sport_filter == "NFL" and not platform_pairs:
        future = []
        for prop in raw_props:
            if str(prop.get("league") or prop.get("sport") or "").upper() != "NFL":
                continue
            game_time = str(prop.get("game_time") or "").strip()
            if game_time and str(prop.get("season_type") or "").lower() != "season_long":
                future.append(game_time)
        next_slate = min(future, default="")
        return {
            "suggestions": [],
            "mode": "waiting_for_nfl_lines",
            "next_available_slate": next_slate,
            "message": (
                "No same-day, full-game NFL player props are posted on the selected platform. "
                + (f"The next provider-backed NFL slate begins {next_slate}. " if next_slate else "")
                + "EdgeIQ keeps future and season-long offers out of today's entry generator and waits for a confirmed matchup and kickoff."
            ),
        }
    suggestions = []
    for platform_model, raw_props in platform_pairs:
        suggestions.extend(
            suggest(
                raw_props,
                sport,
                platform_model,
                limit=5,
                leg_count=leg_count,
                apply_feedback=True,
                diversify=True,
                avoid_prop_keys=avoid_prop_keys or set(),
            )
        )
    serialized = [serialize_suggestion(suggestion) for suggestion in suggestions]
    seen_keys: set[str] = set()
    reused_count = 0
    for suggestion in serialized:
        keys = [_serialized_prop_key(prop) for prop in suggestion.get("entry", {}).get("props", [])]
        reused_count += sum(1 for key in keys if key in seen_keys)
        seen_keys.update(keys)
        suggestion["diversification"] = {
            "prop_keys": keys,
            "reused_from_recent_batch": sum(1 for key in keys if key in (avoid_prop_keys or set())),
        }
    payload = {
        "suggestions": serialized,
        "mode": f"{entry_platform.lower()}_{leg_count}_leg",
        "platform": entry_platform,
        "leg_count": leg_count,
        "maximum_legs": maximum_legs,
        "diversification": {
            "enabled": True,
            "unique_props": len(seen_keys),
            "reused_props": reused_count,
            "recent_props_avoided": len(avoid_prop_keys or set()),
            "message": (
                "Cards favor different props when comparably strong verified alternatives are available."
            ),
        },
        "performance": {"cache_hit": False, "generation_ms": round((time.perf_counter() - started) * 1000.0, 1)},
    }
    with _ENTRY_GENERATOR_LOCK:
        _ENTRY_GENERATOR_CACHE[cache_key] = (now + _ENTRY_GENERATOR_TTL_SECONDS, deepcopy(payload))
        if len(_ENTRY_GENERATOR_CACHE) > 64:
            expired = [key for key, value in _ENTRY_GENERATOR_CACHE.items() if value[0] <= now]
            for key in expired or list(_ENTRY_GENERATOR_CACHE)[:16]:
                _ENTRY_GENERATOR_CACHE.pop(key, None)
    return payload


def _serialized_prop_key(prop: dict) -> str:
    player = canonical_person_key(prop.get("player"))
    stat = str(prop.get("stat") or "").strip().lower().replace(",", "")
    direction = str(prop.get("direction") or "Over").strip().lower()
    return f"{player}|{stat}|{direction}|{float(prop.get('line') or 0.0):.2f}"


def confirmed_entry_suggestions_payload(
    sport: str,
    platform: str,
    *,
    confirmed_props: Callable[[str, str | None, int], dict],
    entry_platform: Callable[[str], object],
    mixed_risk: Callable[[list[dict], str, object], list],
    serialize_suggestion: Callable[[object], dict],
) -> dict:
    payload = confirmed_props(platform, _sport_filter(sport), 80)
    suggestion_sport = sport if sport != "All Sports" else payload["sport"]
    suggestions = mixed_risk(payload["raw_props"], suggestion_sport, entry_platform(platform))
    return {
        "suggestions": [serialize_suggestion(suggestion) for suggestion in suggestions],
        "confirmed_count": payload["count"],
        "platform": platform,
        "sport": sport,
        "mode": "confirmed_props_top_5",
    }


def crazy_six_payload(
    sport: str,
    platform: str,
    *,
    selected_entry_platforms: Callable[[str], list[str]],
    fetch_platform_props: Callable[[str], list[dict]],
    feed_pool: Callable[[list[dict], str | None], list[dict]],
    analyze_prop: Callable[[dict], dict],
    confirm_prop: Callable[[dict, dict], dict | None],
    prop_pool: Callable[[list[dict]], list[dict]],
    entry_platform: Callable[[str], object],
    suggest: Callable[..., list],
    serialize_suggestion: Callable[[object], dict],
    canonical_platform: Callable[[str], str],
    end_to_end_eligibility: Callable[[dict], dict],
    parse_game_time: Callable[[object], object | None],
) -> dict:
    sport_filter = _sport_filter(sport)
    requested_platforms = selected_entry_platforms(platform)
    platform_names = list(dict.fromkeys([*requested_platforms, "PrizePicks", "Underdog"]))
    candidates: list[dict] = []
    available_sports: set[str] = set()
    for platform_name in platform_names:
        raw_props = feed_pool(fetch_platform_props(platform_name), sport_filter)
        confirmed_rows: list[dict] = []
        for raw in raw_props:
            raw_sport = str(raw.get("league") or "").upper()
            if sport_filter and raw_sport != sport_filter:
                continue
            confirmed = confirm_prop(raw, analyze_prop(raw))
            if confirmed is None:
                continue
            confirmed_rows.append(confirmed["_raw"])
            if raw_sport:
                available_sports.add(raw_sport)
            if len(confirmed_rows) >= 20:
                break
        pool = prop_pool(confirmed_rows)
        if len(pool) < 6:
            continue
        suggestions = suggest(
            pool,
            sport_filter or "All Sports",
            entry_platform(platform_name),
            limit=1,
            leg_count=6,
            max_same_team=1,
            exclude_correlated=True,
            apply_feedback=False,
        )
        correlation_relaxed = False
        if not suggestions:
            suggestions = suggest(
                pool,
                sport_filter or "All Sports",
                entry_platform(platform_name),
                limit=1,
                leg_count=6,
                max_same_team=2,
                exclude_correlated=False,
                apply_feedback=False,
            )
            correlation_relaxed = bool(suggestions)
        if suggestions:
            serialized = serialize_suggestion(suggestions[0])
            serialized.update(
                {
                    "risk_tier": "Crazy 6-Leg",
                    "correlation_relaxed": correlation_relaxed,
                    "max_same_team": 2 if correlation_relaxed else 1,
                }
            )
            candidates.append(serialized)
    candidates.sort(
        key=lambda row: (
            float(row.get("score") or 0.0),
            float((row.get("trust") or {}).get("score") or 0.0),
        ),
        reverse=True,
    )
    suggestion = candidates[0] if candidates else None
    props = suggestion.get("entry", {}).get("props", []) if suggestion else []
    suggestion_platform = suggestion.get("entry", {}).get("platform", "") if suggestion else ""
    return {
        "suggestion": suggestion,
        "platform": suggestion.get("entry", {}).get("platform", platform) if suggestion else platform,
        "requested_sport": sport,
        "requested_platform": platform,
        "fallback_platform_used": bool(suggestion)
        and canonical_platform(suggestion_platform) not in {canonical_platform(name) for name in requested_platforms},
        "sports_available": sorted(available_sports),
        "sports_used": sorted({str(prop.get("sport") or "").upper() for prop in props if prop.get("sport")}),
        "verification": {
            "end_to_end_verified": bool(props) and all(end_to_end_eligibility(prop)["eligible"] for prop in props),
            "current_provider_lines": bool(props) and all(prop.get("line") is not None for prop in props),
            "confirmed_game_times": bool(props)
            and all(parse_game_time(prop.get("game_time", "")) is not None for prop in props),
            "settlement_provider": "ESPN official box score",
            "unique_players": len({canonical_person_key(prop.get("player")) for prop in props}) == 6,
        },
        "warning": "Crazy 6-leg entries are high variance. Verified inputs make the card auditable, not safe or guaranteed profitable.",
    }


def optimized_entries_payload(
    platform: str,
    sport: str,
    min_legs: int,
    max_legs: int,
    limit: int,
    min_confidence: float,
    min_edge: float,
    max_same_team: int,
    exclude_correlated: bool,
    apply_feedback: bool,
    *,
    optimize: Callable[..., list],
    value_rank: Callable[[list, str], list[dict]],
    obstacles: Callable[[list[dict]], list],
) -> dict:
    maximum_legs = _maximum_legs(platform)
    if min_legs < 2 or max_legs > maximum_legs or min_legs > max_legs:
        raise RecommendationRequestError(
            f"Use a {platform} leg range between 2 and {maximum_legs}."
        )
    suggestions = optimize(
        platform,
        _sport_filter(sport),
        min_legs,
        max_legs,
        limit,
        min_confidence,
        min_edge,
        max_same_team,
        exclude_correlated,
        apply_feedback,
    )
    serialized = value_rank(suggestions, platform)
    portfolio_ready = [
        suggestion for suggestion in serialized
        if not (suggestion.get("portfolio") or {}).get("conflicts")
    ]
    return {
        "suggestions": serialized,
        "paid_ready_count": sum(
            1 for suggestion in portfolio_ready
            if (suggestion.get("release_status") or {}).get("ok")
        ),
        "portfolio_ready_count": len(portfolio_ready),
        "best_value_pick": serialized[0] if serialized else None,
        "obstacles": obstacles(serialized),
        "platform": platform,
        "sport": sport,
        "min_legs": min_legs,
        "max_legs": max_legs,
        "maximum_legs": maximum_legs,
        "filters": {
            "min_confidence": min_confidence,
            "min_edge": min_edge,
            "max_same_team": max_same_team,
            "exclude_correlated": exclude_correlated,
            "apply_feedback": apply_feedback,
        },
    }


def _sport_filter(sport: str) -> str | None:
    return None if sport == "All Sports" else sport.upper()


def _maximum_legs(platform: str) -> int:
    key = str(platform or "").strip().lower()
    if key == "underdog":
        return 8
    if key in {"prizepicks", "draftkings pick6"}:
        return 6
    return 5
