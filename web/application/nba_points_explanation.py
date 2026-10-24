"""On-demand NBA points explanations from fixed research facts."""

from __future__ import annotations

import json
from collections.abc import Callable

from services.ollama_client import ollama_enabled, ollama_role_model, ollama_structured


def build_nba_points_explanation(
    player: str,
    line: float,
    platform: str,
    detail: str,
    *,
    research: Callable[[str, str, str, str, float], dict],
    prioritize: Callable[[list[dict]], list[str] | None] | None = None,
) -> dict:
    if detail not in {"concise", "detailed"}:
        raise ValueError("Choose a concise or detailed explanation.")
    payload = research(player, "Points", "NBA", platform, line)
    intelligence = payload.get("nba_points_intelligence") or {}
    if not intelligence or payload.get("line") != line:
        return {"status": "unavailable", "reason": "NBA points research is unavailable for this exact line."}

    verified = (intelligence.get("thresholds") or {}).get("verified_season") or {}
    games = int(verified.get("games") or 0)
    custom = verified.get("custom_line") or {}
    forecast = payload.get("forecast") or {}
    facts = [
        {"id": "history", "text": f"{games} verified regular-season points games are available for {player}.", "weight": 1},
    ]
    if custom.get("decisions"):
        facts.append({
            "id": "hit_rate",
            "text": (
                f"Over {line:g} points hit in {custom['hits']} of {custom['decisions']} decided "
                f"regular-season games; {custom.get('pushes') or 0} pushed. This is past frequency, not the next-game probability."
            ),
            "weight": 2,
        })
    if forecast.get("source") == "verified_history_distribution":
        facts.append({
            "id": "forecast",
            "text": f"EdgeIQ's separate points forecast is {float(forecast['projection']):g}; its model probability is not the historical hit rate.",
            "weight": 3,
        })
    else:
        facts.append({
            "id": "forecast",
            "text": "An independent points forecast is unavailable; the entered line is only a market reference.",
            "weight": 3,
        })
    matchup = intelligence.get("matchup") or {}
    defense = matchup.get("team_points_allowed") or {}
    if matchup.get("opponent") and defense.get("sample_size"):
        facts.append({
            "id": "defense",
            "text": (
                f"Against {matchup['opponent']}, verified pregame team finals show "
                f"{defense['last_10']:g} points allowed on average over the recent sample. "
                "This is team-level context, not a player matchup adjustment."
            ),
            "weight": 4,
        })
    facts.append({
        "id": "market",
        "text": "An exact sportsbook payout and validated expected value are unavailable in this research view.",
        "weight": 5,
    })
    ordered_ids = [fact["id"] for fact in facts]
    ranked = prioritize(facts) if prioritize is not None else _ollama_priorities(facts)
    if ranked and len(set(ranked)) == len(ranked) and set(ranked) == set(ordered_ids):
        ordered_ids = ranked
        source = "ollama_prioritized"
    else:
        source = "deterministic_fallback"
    by_id = {fact["id"]: fact["text"] for fact in facts}
    # Always show the evidence limit, regardless of how the local model ranks facts.
    selected = ordered_ids[:2] if detail == "concise" else ordered_ids
    if "market" not in selected:
        selected.append("market")
    return {
        "status": "research_only",
        "source": source,
        "detail": detail,
        "player": player,
        "line": line,
        "bullets": [by_id[key] for key in selected],
        "model_changed": False,
    }


def _ollama_priorities(facts: list[dict]) -> list[str] | None:
    if not ollama_enabled():
        return None
    ids = [fact["id"] for fact in facts]
    schema = {
        "type": "object",
        "properties": {"ordered_ids": {"type": "array", "items": {"type": "string", "enum": ids}}},
        "required": ["ordered_ids"],
    }
    result, _ = ollama_structured(
        [
            {"role": "system", "content": "Rank the supplied verified fact IDs by relevance. Return every ID once. Do not write claims or recalculate values."},
            {"role": "user", "content": json.dumps(facts)},
        ],
        schema,
        model=ollama_role_model("analyst"),
        timeout=8,
    )
    return result.get("ordered_ids") if isinstance(result, dict) else None
