"""Bounded, inspectable selection of player-research evidence for the analyst."""

from __future__ import annotations

from utils.config_bounds import bounded_env_int

MAX_ANALYST_EVIDENCE = 9
PRIORITY_TYPES = (
    "provider_market", "probability_forecast", "final_stat", "role_and_lineup",
    "line_movement", "availability", "game_context",
)
QUESTION_TYPES = {
    "injur": "availability", "lineup": "availability", "weather": "availability",
    "minutes": "role_and_lineup", "role": "role_and_lineup",
    "movement": "line_movement", "closing": "line_movement",
    "history": "final_stat", "last game": "final_stat", "opponent": "final_stat",
}


def rank_player_evidence(rows: list[dict], context: dict, question: str, limit: int = MAX_ANALYST_EVIDENCE) -> list[dict]:
    """Prefer exact, fresh, verified facts and preserve distinct evidence kinds."""
    requested = str(question or "").casefold()
    wanted = {kind for token, kind in QUESTION_TYPES.items() if token in requested}
    recommendation = context.get("recommendation") or {}
    game = str(recommendation.get("game") or "").casefold()
    sport = str(context.get("sport") or "").casefold()
    stat = str(context.get("stat") or "").casefold()
    platform = str(context.get("platform") or "").casefold()
    requested_line = (context.get("query_context") or {}).get("requested_line")
    recommended_line = recommendation.get("line")
    scored: list[tuple[int, int, dict]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        kind = str(row.get("type") or "")
        if kind in {"provider_market", "availability", "line_movement"} and row.get("fresh") is not True:
            continue
        reasons = []
        score = 0
        if game and str(row.get("game") or "").casefold() == game:
            score += 40
            reasons.append("same game")
        payload = row.get("payload") or {}
        if (kind == "provider_market" and requested_line is not None and isinstance(payload, dict)
                and _same_line(payload.get("line"), requested_line)):
            score += 25
            reasons.append("requested posted line")
        elif (kind == "provider_market" and recommended_line is not None and isinstance(payload, dict)
              and _same_line(payload.get("line"), recommended_line)):
            score += 10
            reasons.append("recommended posted line")
        if kind in PRIORITY_TYPES:
            score += 15
            reasons.append("decision evidence")
        if kind in wanted:
            score += 25
            reasons.append("question match")
        if row.get("fresh") is True:
            score += 10
            reasons.append("within evidence TTL")
        if kind == "final_stat" or row.get("source_kind") == "derived_verified_history":
            score += 10
            reasons.append("verified history")
        if sport and str(row.get("sport") or "").casefold() == sport:
            score += 5
        if stat and str(row.get("stat") or "").casefold() == stat:
            score += 5
        if platform and str(row.get("platform") or "").casefold() == platform:
            score += 5
        ranked_row = {**row, "selection_score": score, "selection_reason": ", ".join(reasons) or "recent context"}
        scored.append((score, index, ranked_row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict] = []
    seen_types: set[str] = set()
    cap = max(1, min(int(limit), bounded_env_int("EDGEIQ_COPILOT_MAX_EVIDENCE", MAX_ANALYST_EVIDENCE, 1, MAX_ANALYST_EVIDENCE)))
    for _, _, row in scored:
        kind = str(row.get("type") or "")
        if kind in PRIORITY_TYPES and kind not in seen_types:
            selected.append(row)
            seen_types.add(kind)
            if len(selected) >= cap:
                return selected
    selected_ids = {row["id"] for row in selected}
    for _, _, row in scored:
        if row["id"] not in selected_ids:
            selected.append(row)
            selected_ids.add(row["id"])
            if len(selected) >= cap:
                break
    return selected


def _same_line(left: object, right: object) -> bool:
    try:
        return abs(float(str(left)) - float(str(right))) < 0.001
    except (TypeError, ValueError):
        return False
