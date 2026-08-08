from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from analytics.ev import expected_value, sportsbook_probability
from analytics.hit_rate import estimate_hit_rate
from analytics.kelly import breakeven_probability, half_kelly, kelly_fraction, suggested_wager
from analytics.projection import auto_projection
from analytics.prop_metrics import calculate_confidence, calculate_directional_edge
from analytics.recommendation import recommendation as ev_recommendation
from web.schemas import AiEntryReviewPayload, EvPayload, ParlayChatPayload, ProjectionAssistPayload


class LocalModelPick(Protocol):
    suggestion: dict
    score: float
    reasons: list[str]
    cautions: list[str]


def parlay_chat_payload(
    payload: ParlayChatPayload,
    *,
    parse_request: Callable[[str, str], dict],
    find_suggestions: Callable[..., tuple[list, dict]],
    serialize_suggestion: Callable[[object], dict],
    local_response: Callable[[list[dict], dict], tuple[str, LocalModelPick | None]],
    openai_response: Callable[[str, list[dict], dict], tuple[str | None, str | None]],
    openai_model: Callable[[], str],
    local_model_version: str,
    local_model_card: Callable[[list[dict]], dict],
) -> dict:
    request = parse_request(payload.message, payload.sport)
    suggestions, search = find_suggestions(payload.platform, request)
    if not suggestions:
        suggestions, search = find_suggestions(
            payload.platform,
            {**request, "confirmed_only": False, "risk_profile": "balanced"},
            relaxed=True,
        )
    serialized = [serialize_suggestion(suggestion) for suggestion in suggestions]
    local_message, local_pick = local_response(serialized, request)
    ai_text, ai_error = openai_response(payload.message, serialized, request)
    selected = local_pick.suggestion if local_pick else (serialized[0] if serialized else None)
    return {
        "message": ai_text or local_message,
        "suggestion": selected,
        "candidates": serialized,
        "alternatives": [candidate for candidate in serialized if candidate is not selected][:3],
        "ai_enabled": ai_text is not None,
        "model": openai_model() if ai_text else local_model_version,
        "local_model": {
            **local_model_card(serialized),
            "selected_score": local_pick.score if local_pick else 0.0,
            "reasons": local_pick.reasons if local_pick else [],
            "cautions": local_pick.cautions if local_pick else [],
        },
        "ai_error": ai_error,
        "request": request,
        "search": search,
    }


def ai_status_payload(
    api_key: str,
    *,
    openai_model: Callable[[], str],
    openai_vision_model: Callable[[], str],
    local_model_version: str,
) -> dict:
    key = api_key.strip()
    return {
        "configured": bool(key),
        "key_format_ok": key.startswith("sk-"),
        "model": openai_model(),
        "vision_model": openai_vision_model(),
        "local_model": {
            "available": True,
            "model": local_model_version,
            "purpose": "Offline parlay ranking and recommendation fallback.",
        },
        "note": (
            "OpenAI key is present and has the expected prefix."
            if key.startswith("sk-")
            else "OpenAI key is missing or invalid; EdgeIQ Local remains available for recommendations."
        ),
    }


def entry_review_payload(
    payload: AiEntryReviewPayload,
    *,
    entry_from_payload: Callable[[AiEntryReviewPayload], object],
    analyze_entry: Callable[[object], dict],
    fallback_review: Callable[[dict], str],
    openai_review: Callable[[str, dict], tuple[str | None, str | None]],
    openai_model: Callable[[], str],
    local_model_version: str,
) -> dict:
    analysis = analyze_entry(entry_from_payload(payload))
    fallback = fallback_review(analysis)
    ai_text, ai_error = openai_review(payload.question, analysis)
    return {
        "review": ai_text or fallback,
        "analysis": analysis,
        "ai_enabled": ai_text is not None,
        "model": openai_model() if ai_text else local_model_version,
        "ai_error": ai_error,
    }


def trending_games_response(
    platform: str,
    sport: str,
    limit: int,
    *,
    fetch_props: Callable[[str, str | None], list[dict]],
    top_props_by_sport: Callable[[list[dict], int, str | None], list[dict]],
    build_games: Callable[[list[dict], list[dict], int], list[dict]],
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    props = fetch_props(platform, sport_filter)
    props.sort(key=lambda prop: prop.get("trending_count", 0), reverse=True)
    ranked_props = top_props_by_sport(props, 5, sport_filter)
    games = build_games(props, ranked_props, limit)
    return {
        "games": games,
        "platform": platform,
        "sport": sport,
        "ranked_player_count": len({prop.get("player", "") for prop in ranked_props}),
    }


def game_context_response(
    game: str,
    sport: str,
    platform: str,
    *,
    build_context: Callable[[str, str | None, str], dict],
) -> dict:
    sport_filter = None if sport == "All Sports" else sport.upper()
    return build_context(game, sport_filter, platform)


def ev_analysis_payload(payload: EvPayload, *, bankroll: Callable[[], float]) -> dict:
    probability_decimal = payload.probability / 100
    sportsbook = sportsbook_probability(payload.odds) * 100
    ev_percent = expected_value(payload.odds, probability_decimal) * 100
    edge = payload.probability - sportsbook
    return {
        "sportsbook_probability": round(sportsbook, 2),
        "edge": round(edge, 2),
        "expected_value": round(ev_percent, 2),
        "break_even": round(breakeven_probability(payload.odds) * 100, 2),
        "full_kelly": round(kelly_fraction(payload.odds, probability_decimal) * 100, 2),
        "half_kelly": round(half_kelly(payload.odds, probability_decimal) * 100, 2),
        "suggested_wager": suggested_wager(payload.odds, probability_decimal, bankroll()),
        "recommendation": ev_recommendation(ev_percent),
    }


def projection_assist_payload(payload: ProjectionAssistPayload) -> dict:
    projection = payload.projection
    if projection is None:
        projection = auto_projection(payload.line, payload.trending_count)
    hit_rate = estimate_hit_rate(
        payload.player,
        payload.stat,
        payload.line,
        projection,
        payload.trending_count,
        payload.sport,
        direction=payload.direction,
    )
    edge = calculate_directional_edge(payload.line, projection, payload.direction)
    confidence = calculate_confidence(edge)
    grade = "A" if confidence >= 70 else "B" if confidence >= 60 else "C" if confidence >= 52 else "D"
    return {
        "player": payload.player,
        "sport": payload.sport,
        "stat": payload.stat,
        "line": payload.line,
        "projection": round(projection, 2),
        "edge": round(edge, 2),
        "confidence": round(confidence, 2),
        "estimated_hit_rate": hit_rate.estimated_hit_rate,
        "grade": grade,
        "source": hit_rate.source,
        "recommendation": "Consider" if confidence >= 60 and hit_rate.estimated_hit_rate >= 55 else "Watchlist",
        "reason": (
            f"Projection model sees {edge:+.2f} edge with {hit_rate.source} hit-rate context. "
            "Past betting history improves this once imported because calibration can learn where your confidence has been too high or too low."
        ),
    }
