from __future__ import annotations

from dataclasses import dataclass

MODEL_NAME = "EdgeIQ Local"
MODEL_VERSION = "edgeiq-local-v1.0"


@dataclass(frozen=True)
class LocalModelPick:
    suggestion: dict
    score: float
    reasons: list[str]
    cautions: list[str]


def rank_suggestions(suggestions: list[dict]) -> list[LocalModelPick]:
    """Rank serialized entry suggestions without calling an external LLM."""
    picks = [
        LocalModelPick(
            suggestion=suggestion,
            score=round(_local_score(suggestion), 2),
            reasons=_reasons(suggestion),
            cautions=_cautions(suggestion),
        )
        for suggestion in suggestions
    ]
    return sorted(picks, key=lambda pick: pick.score, reverse=True)


def best_suggestion(suggestions: list[dict]) -> LocalModelPick | None:
    ranked = rank_suggestions(suggestions)
    return ranked[0] if ranked else None


def compose_parlay_response(suggestions: list[dict], request: dict | None = None) -> tuple[str, LocalModelPick | None]:
    request = request or {"leg_count": 3, "sport_label": "current filters"}
    leg_count = int(request.get("leg_count") or 3)
    sport_label = request.get("sport_label") or "current filters"
    pick = best_suggestion(suggestions)
    if pick is None:
        return f"I could not find a {leg_count}-leg parlay for {sport_label}. Try another sport or platform.", None

    suggestion = pick.suggestion
    legs = suggestion.get("entry", {}).get("props", [])
    leg_text = ", ".join(
        f"{prop.get('player', 'Player')} {prop.get('direction', 'Over')} {prop.get('stat', 'Prop')} {prop.get('line', '')}".strip()
        for prop in legs
    )
    reasons = "; ".join(pick.reasons[:3]) or "best available blend of confidence, edge, and data quality"
    cautions = "; ".join(pick.cautions[:2])
    caution_text = f" Watchouts: {cautions}." if cautions else " Still review injuries, news, and your bankroll before placing it."
    return (
        f"My best {leg_count}-leg parlay for {sport_label} is {leg_text}. "
        f"EdgeIQ Local rates it {suggestion.get('grade', '-')} with a {pick.score:.1f} model score. "
        f"Why: {reasons}.{caution_text}"
    ), pick


def model_card(suggestions: list[dict]) -> dict:
    ranked = rank_suggestions(suggestions)
    return {
        "name": MODEL_NAME,
        "version": MODEL_VERSION,
        "mode": "offline_recommendation_model",
        "candidate_count": len(suggestions),
        "top_score": ranked[0].score if ranked else 0.0,
        "features": [
            "projected_edge",
            "confidence",
            "historical_feedback",
            "data_quality",
            "source_signals",
            "correlation_penalty",
            "market_trending",
        ],
    }


def _local_score(suggestion: dict) -> float:
    entry = suggestion.get("entry", {})
    props = entry.get("props", [])
    if not props:
        return float(suggestion.get("score") or 0.0)

    avg_confidence = float(entry.get("average_confidence") or _average(props, "confidence"))
    avg_edge = float(entry.get("average_edge") or _average(props, "edge"))
    avg_quality = _average_nested(props, "data_quality", "score", default=50.0)
    source_bonus = min(8.0, sum(len(prop.get("source_signals") or []) for prop in props) * 1.5)
    hit_rate_bonus = _hit_rate_bonus(props)
    trend_bonus = min(6.0, sum(float(prop.get("trending_count") or 0.0) for prop in props) / 60000.0)
    warning_penalty = len(suggestion.get("warnings") or []) * 7.0
    leg_penalty = max(0, int(suggestion.get("leg_count") or len(props)) - 3) * 2.5
    grade_bonus = {"A": 8.0, "B": 4.0, "C": 1.0, "D": -4.0, "F": -10.0}.get(str(suggestion.get("grade", "")).upper(), 0.0)

    return (
        avg_confidence * 0.58
        + avg_edge * 8.0
        + avg_quality * 0.18
        + source_bonus
        + hit_rate_bonus
        + trend_bonus
        + grade_bonus
        - warning_penalty
        - leg_penalty
    )


def _reasons(suggestion: dict) -> list[str]:
    entry = suggestion.get("entry", {})
    props = entry.get("props", [])
    reasons = []
    avg_confidence = float(entry.get("average_confidence") or _average(props, "confidence"))
    avg_edge = float(entry.get("average_edge") or _average(props, "edge"))
    if avg_confidence >= 60:
        reasons.append(f"{avg_confidence:.1f}% average confidence")
    if avg_edge > 0:
        reasons.append(f"{avg_edge:+.2f} average projected edge")
    quality = _average_nested(props, "data_quality", "score", default=0.0)
    if quality >= 65:
        reasons.append(f"{quality:.0f}/100 average data quality")
    source_count = sum(len(prop.get("source_signals") or []) for prop in props)
    if source_count:
        reasons.append(f"{source_count} supporting source signals")
    if any(float(prop.get("trending_count") or 0.0) > 10000 for prop in props):
        reasons.append("strong market interest")
    return reasons


def _cautions(suggestion: dict) -> list[str]:
    props = suggestion.get("entry", {}).get("props", [])
    cautions = list(suggestion.get("warnings") or [])
    if int(suggestion.get("leg_count") or len(props)) >= 4:
        cautions.append("higher variance because this is a long entry")
    thin = [
        prop.get("player", "A leg")
        for prop in props
        if float((prop.get("data_quality") or {}).get("score") or 0.0) < 55
    ]
    if thin:
        cautions.append(f"thin data on {thin[0]}")
    if any(abs(float(prop.get("edge") or 0.0)) < 0.5 for prop in props):
        cautions.append("at least one leg has a thin projected edge")
    return cautions[:4]


def _hit_rate_bonus(props: list[dict]) -> float:
    bonus = 0.0
    for prop in props:
        espn = prop.get("espn") or {}
        hit_rate = espn.get("hit_rate")
        sample_size = int(espn.get("sample_size") or 0)
        if hit_rate is None or sample_size <= 0:
            continue
        bonus += max(-3.0, min(5.0, (float(hit_rate) - 50.0) * 0.12))
    return max(-6.0, min(10.0, bonus))


def _average(props: list[dict], key: str) -> float:
    values = [float(prop.get(key) or 0.0) for prop in props]
    return sum(values) / len(values) if values else 0.0


def _average_nested(props: list[dict], parent: str, key: str, default: float = 0.0) -> float:
    values = [
        float((prop.get(parent) or {}).get(key) if (prop.get(parent) or {}).get(key) is not None else default)
        for prop in props
    ]
    return sum(values) / len(values) if values else default
