from typing import Literal

from pydantic import BaseModel, Field


class PropPayload(BaseModel):
    player: str
    player_identity_id: int | None = None
    player_provider: str = ""
    provider_player_id: str = ""
    team: str = ""
    position: str = ""
    sport: str
    stat: str
    line: float
    baseline_line: float | None = None
    standard_line: float | None = None
    line_offer_type: str = "standard"
    adjusted_line: bool = False
    is_discounted_line: bool = False
    is_premium_line: bool = False
    line_discount: float = 0.0
    projection: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    projection_source: str = ""
    auto_projected: bool = False
    direction: Literal["Over", "Under"] | None = None
    platform: str = "PrizePicks"
    game: str = ""
    game_time: str = ""
    season_type: str = ""
    trending_count: int = 0
    model_version: str = ""
    feature_as_of: str = ""
    forecast_snapshot: dict = Field(default_factory=dict)
    forecast_paid_eligible: bool = False


class EntryPayload(BaseModel):
    platform: str = "PrizePicks"
    wager: float = Field(default=0.0, ge=0)
    multiplier: float = Field(default=1.0, ge=1)
    payout_type: Literal["standard", "flex"] = "standard"
    payout_schedule: dict[str, float] = Field(default_factory=dict)
    recommended_by_app: bool = False
    entry_mode: Literal["real", "paper"] = "real"
    props: list[PropPayload]


class ShareSlipPayload(EntryPayload):
    note: str = ""


class AutoPaperCalibrationPayload(BaseModel):
    platform: str = "PrizePicks"
    sport: str = "All Sports"
    leg_count: int = Field(default=2, ge=2, le=5)
    max_entries: int = Field(default=3, ge=1, le=10)
    prefer_confirmed: bool = True
    dry_run: bool = False


class AiEntryReviewPayload(EntryPayload):
    question: str = "Should I place this entry?"


class SettlePayload(BaseModel):
    result: Literal["Win", "Loss", "Push", "DNP"]
    dnp_legs: int = Field(default=0, ge=0)


class BetPayload(BaseModel):
    sport: str
    game: str
    description: str
    odds: int
    wager: float = Field(gt=0)
    result: Literal["Win", "Loss", "Push"]
    platform: str = ""
    stat_type: str = ""
    win_probability: float = 0
