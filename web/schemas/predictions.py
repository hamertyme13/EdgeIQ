from typing import Literal

from pydantic import BaseModel, Field


class ProjectionAssistPayload(BaseModel):
    player: str
    sport: str = "WNBA"
    stat: str
    line: float
    projection: float | None = None
    trending_count: int = 0
    direction: Literal["Over", "Under"] = "Over"


class ParlayChatPayload(BaseModel):
    message: str = "you need a parlay?"
    platform: str = "PrizePicks"
    sport: str = "All Sports"


class CopilotQueryPayload(BaseModel):
    question: str = "What should I know before placing an entry?"
    player: str = ""
    stat: str = ""
    sport: str = "All Sports"
    platform: str = "Both"
    line: float | None = None


class RecommendationExplainPayload(BaseModel):
    question: str = "Why is this recommended and what could make it lose?"
    suggestion: dict
    alternatives: list[dict] = Field(default_factory=list)


class ModelEvaluationPayload(BaseModel):
    model: str = ""


class WatchlistItemPayload(BaseModel):
    player: str
    sport: str = "All Sports"
    stat: str = ""
    platform: str = "PrizePicks"
    direction: Literal["Over", "Under", "Any"] = "Any"
    target_line: float | None = None
    alert_when: Literal["at_or_better", "moves_by", "available"] = "at_or_better"
    move_threshold: float = Field(default=1.0, ge=0)
    note: str = ""


class BoostAnalysisPayload(BaseModel):
    player: str
    sport: str
    stat: str
    platform: str = "PrizePicks"
    direction: Literal["Over", "Under"] = "Over"
    original_line: float
    boosted_line: float
    odds: int = -110


class HedgeCalculatorPayload(BaseModel):
    original_odds: int
    hedge_odds: int
    original_stake: float = Field(ge=0)
    target: Literal["guarantee", "free_roll", "min_loss"] = "guarantee"


class MiddleCalculatorPayload(BaseModel):
    over_line: float
    under_line: float
    over_odds: int = -110
    under_odds: int = -110
    over_stake: float = Field(default=10.0, ge=0)
    under_stake: float = Field(default=10.0, ge=0)


class EvPayload(BaseModel):
    odds: int
    probability: float = Field(ge=0, le=100)
