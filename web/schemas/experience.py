from typing import Any

from pydantic import BaseModel, Field


class ProductEventPayload(BaseModel):
    event_name: str = Field(min_length=2, max_length=80)
    entity_type: str = Field(default="", max_length=40)
    entity_id: str = Field(default="", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchHistoryPayload(BaseModel):
    player: str = Field(min_length=1, max_length=160)
    sport: str = Field(default="", max_length=30)
    stat: str = Field(default="", max_length=120)
    platform: str = Field(default="", max_length=80)
    line: float | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class OnboardingPayload(BaseModel):
    bankroll: float = Field(default=0, ge=0)
    platform: str = "PrizePicks"
    sport: str = "All Sports"
    risk: str = "balanced"
    default_wager: float = Field(default=0, ge=0)
    complete: bool = True
