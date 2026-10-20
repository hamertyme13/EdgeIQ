"""Small, source-linked numeric facts for Ask EdgeIQ's detailed view."""

from __future__ import annotations

from math import isfinite


def quantitative_facts(bundle: dict) -> list[dict]:
    summary = bundle.get("summary") or {}
    intent = bundle.get("intent")
    if intent == "daily_briefing":
        rows = summary.get("top_opportunities") or []
        citation_id = "briefing-snapshot"
    elif intent == "player_research":
        rows = [summary.get("recommendation") or {}]
        citation_id = "current-market"
    else:
        return []
    facts: list[dict] = []
    fields = (("line", "Line"), ("projection", "Model projection"), ("confidence", "Displayed confidence"))
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        subject = str(row.get("player") or summary.get("query_context", {}).get("player") or "Selected prop")
        for field, label in fields:
            raw = row.get(field)
            if isinstance(raw, bool) or raw is None:
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            if isfinite(number):
                facts.append({"subject": subject, "label": label, "value": number, "citation_id": citation_id})
    return facts
