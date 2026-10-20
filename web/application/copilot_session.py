"""Resolve a narrow, browser-supplied player focus without server-side chat memory."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

from web.application.copilot_commands import SPORTS
from web.schemas.predictions import CopilotFocus, CopilotQueryPayload

FOCUS_TTL = timedelta(minutes=45)
STAT_WORDS = {
    "points": "Points", "rebounds": "Rebounds", "assists": "Assists",
    "steals": "Steals", "blocks": "Blocks", "strikeouts": "Strikeouts",
    "hits": "Hits", "runs": "Runs", "yards": "Yards",
}


def resolve_followup(payload: CopilotQueryPayload, *, now: datetime | None = None) -> tuple[CopilotQueryPayload, bool]:
    """Use a recent explicit player focus only for an unambiguous stat follow-up."""
    question = payload.question.casefold().strip()
    mentions_focus = bool(re.search(r"\b(her|his|their|that player|same player)\b", question))
    matches = {label for word, label in STAT_WORDS.items() if re.search(rf"\b{word}\b", question)}
    about_stat = bool(re.search(r"\bwhat about\b", question)) and bool(matches)
    if payload.player.strip() or not (mentions_focus or about_stat):
        return payload, False
    if len(matches) != 1:
        return payload, True
    focus = payload.focus
    current = now or datetime.now(UTC)
    if not focus or focus.updated_at.tzinfo is None or current - focus.updated_at > FOCUS_TTL:
        return payload, True
    if focus.updated_at > current + timedelta(minutes=1):
        return payload, True
    if focus.sport not in SPORTS or payload.sport != focus.sport or payload.platform != focus.platform:
        return payload, True
    stat = matches.pop()
    return payload.model_copy(update={
        "player": focus.player, "stat": stat,
        "line": payload.line if stat == focus.stat else None,
    }), False


def focus_from_research(payload: CopilotQueryPayload, evidence: dict) -> CopilotFocus | None:
    if payload.sport not in SPORTS or not (evidence.get("history_count") or evidence.get("recommendation")):
        return None
    return CopilotFocus(
        player=str((evidence.get("recommendation") or {}).get("player") or evidence.get("player") or payload.player),
        sport=payload.sport, platform=payload.platform, stat=payload.stat,
        updated_at=datetime.now(UTC),
    )
