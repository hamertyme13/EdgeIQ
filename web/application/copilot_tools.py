"""Typed, bounded access to existing read-only copilot evidence sources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.recommendation_timeline import recommendation_timeline
from web.application.copilot_commands import SPORTS
from web.application.model_track_record import model_track_record
from web.application.personal_edge_service import personal_edge_payload


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BriefingInput(ToolInput):
    platform: str = Field(max_length=40)
    sport: str | None = None

    @field_validator("sport")
    @classmethod
    def known_sport(cls, value: str | None) -> str | None:
        if value is not None and value not in SPORTS:
            raise ValueError("Unknown sport")
        return value


class TimelineInput(ToolInput):
    player: str = Field(min_length=1, max_length=100)
    sport: str = ""
    stat: str = Field(default="", max_length=100)
    limit: int = Field(default=30, ge=1, le=30)

    @field_validator("sport")
    @classmethod
    def known_sport(cls, value: str) -> str:
        if value and value not in SPORTS:
            raise ValueError("Unknown sport")
        return value


class TrackRecordInput(ToolInput):
    sport: str
    stat: str = Field(default="", max_length=100)

    @field_validator("sport")
    @classmethod
    def known_sport(cls, value: str) -> str:
        if value not in SPORTS:
            raise ValueError("Unknown sport")
        return value


class PersonalEdgeInput(ToolInput):
    mode: Literal["real"] = "real"


class NoInput(ToolInput):
    pass


@dataclass(frozen=True)
class ToolContext:
    cached_briefing: Callable[[str, str | None], dict]
    portfolio: Callable[[], dict]
    personal_edge: Callable[[str], dict] = personal_edge_payload
    timeline: Callable[..., dict] = recommendation_timeline
    track_record: Callable[..., dict] = model_track_record


TOOL_INPUTS: dict[str, type[ToolInput]] = {
    "cached_briefing": BriefingInput,
    "portfolio_risk": NoInput,
    "personal_edge": PersonalEdgeInput,
    "recommendation_timeline": TimelineInput,
    "model_track_record": TrackRecordInput,
}


def invoke_tool(name: str, arguments: dict, context: ToolContext) -> dict:
    """Reject unknown operations before validating or invoking a trusted callback."""
    schema = TOOL_INPUTS.get(name)
    if schema is None:
        raise ValueError("This copilot tool is not available")
    args = schema.model_validate(arguments)
    if name == "cached_briefing":
        assert isinstance(args, BriefingInput)
        raw = context.cached_briefing(args.platform, args.sport)
        return {"top_opportunities": (raw.get("top_opportunities") or [])[:9],
                "slate_changes": raw.get("slate_changes") or {}, "as_of": raw.get("as_of"),
                "cache": {"stale": bool((raw.get("cache") or {}).get("stale"))}}
    if name == "portfolio_risk":
        return context.portfolio()
    if name == "personal_edge":
        assert isinstance(args, PersonalEdgeInput)
        return context.personal_edge(args.mode)
    if name == "recommendation_timeline":
        assert isinstance(args, TimelineInput)
        return context.timeline(**args.model_dump())
    assert isinstance(args, TrackRecordInput)
    return context.track_record(**args.model_dump())
