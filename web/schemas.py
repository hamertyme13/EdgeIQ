from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BankrollPayload(BaseModel):
    amount: float = Field(gt=0)


class BankrollTransactionPayload(BaseModel):
    transaction_type: Literal["Deposit", "Withdrawal"]
    amount: float = Field(gt=0)
    note: str = ""


class DnpSettingPayload(BaseModel):
    mode: Literal["reduce", "refund", "ignore"] = "reduce"


class FinalStatsPayload(BaseModel):
    payload: str
    source: str = "manual"


class BettingHistoryPayload(BaseModel):
    payload: str
    source: str = "manual"


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


class UploadAnalyzePayload(BaseModel):
    file_name: str
    content_base64: str
    mime_type: str = ""
    target: Literal["entry", "props", "final_stats", "bet_history"] = "entry"
    source: str = "upload"


class UserPreferencePayload(BaseModel):
    risk_style: Literal["conservative", "balanced", "aggressive"] = "balanced"
    preferred_legs: Literal["2", "3", "2-3", "2-5"] = "2-3"
    allow_high_risk: bool = True
    avoid_same_game: bool = True
    max_wager_pct: float = Field(default=5.0, ge=0.1, le=100)
    default_platform: str = "PrizePicks"
    default_sport: str = "All Sports"
    display_name: str = "Joshua"


class ProviderWeightsPayload(BaseModel):
    weights: dict[str, float]


class RefreshSchedulePayload(BaseModel):
    morning_scan: str = "08:00"
    injury_refresh: str = "11:00"
    line_snapshots: str = "*/30"
    result_check: str = "23:30"
    nightly_calibration: str = "02:00"
    enabled: bool = True


class LossProtectionSettingPayload(BaseModel):
    enabled: bool = True


class BankrollStrategyPayload(BaseModel):
    mode: Literal["flat", "conservative", "balanced", "aggressive", "kelly", "paper"] = "balanced"
    unit_size: float = Field(default=10.0, ge=0)
    max_wager_pct: float = Field(default=5.0, ge=0.1, le=100)
    max_open_exposure_pct: float = Field(default=15.0, ge=0.1, le=100)
    stop_loss_pct: float = Field(default=12.0, ge=0.1, le=100)
    paper_first: bool = False


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


class AlertDeliveryPayload(BaseModel):
    browser_enabled: bool = True
    email_enabled: bool = False
    email_address: str = ""
    sms_enabled: bool = False
    sms_number: str = ""
    webhook_enabled: bool = False
    webhook_url: str = ""
    min_priority: float = Field(default=65.0, ge=0, le=100)
    channels: list[str] = Field(default_factory=list)


class AlertDeliveryTestPayload(BaseModel):
    title: str = "EdgeIQ alert test"
    message: str = "Alert delivery is connected."
    priority: float = Field(default=70.0, ge=0, le=100)
    severity: Literal["neutral", "positive", "warning", "danger"] = "positive"


class EvPayload(BaseModel):
    odds: int
    probability: float = Field(ge=0, le=100)


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
