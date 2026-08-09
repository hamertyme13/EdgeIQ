from typing import Literal

from pydantic import BaseModel, Field


class DnpSettingPayload(BaseModel):
    mode: Literal["reduce", "refund", "ignore"] = "reduce"


class UserPreferencePayload(BaseModel):
    risk_style: Literal["conservative", "balanced", "aggressive"] = "balanced"
    preferred_legs: Literal["2", "3", "2-3", "2-5", "2-6", "2-8"] = "2-3"
    allow_high_risk: bool = True
    avoid_same_game: bool = True
    max_wager_pct: float = Field(default=5.0, ge=0.1, le=100)
    default_platform: str = "PrizePicks"
    default_sport: str = "All Sports"
    display_name: str = "Joshua"


class RefreshSchedulePayload(BaseModel):
    morning_scan: str = "08:00"
    injury_refresh: str = "11:00"
    line_snapshots: str = "*/30"
    result_check: str = "23:30"
    nightly_calibration: str = "02:00"
    enabled: bool = True


class LossProtectionSettingPayload(BaseModel):
    enabled: bool = True


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
