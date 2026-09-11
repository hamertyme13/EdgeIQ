from typing import Any, Literal

from pydantic import BaseModel, Field


class BetaLoginPayload(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=256)


class BetaUserCreatePayload(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=256)
    role: Literal["ADMIN", "BETA_TESTER"] = "BETA_TESTER"
    beta_cohort: str = Field(default="FOUNDING_25", min_length=2, max_length=40)
    is_beta_tester: bool = True


class BetaUserUpdatePayload(BaseModel):
    is_active: bool | None = None
    beta_cohort: str | None = Field(default=None, min_length=2, max_length=40)


class BetaFeedbackPayload(BaseModel):
    prediction_record_id: int | None = Field(default=None, gt=0)
    entry_id: int | None = Field(default=None, gt=0)
    entry_prop_id: int | None = Field(default=None, gt=0)
    useful: bool | None = None
    initial_pick: Literal["Over", "Under", "Unsure"]
    final_pick: Literal["Over", "Under", "Pass"]
    would_pick: Literal["Yes", "No", "Unsure"]
    would_pay: Literal[
        "",
        "Free",
        "$9.99/month",
        "$19.99/month",
        "$29.99/month",
        "$49.99/month",
        "I would not subscribe",
    ] = ""
    feedback_text: str = Field(default="", max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class BetaIssuePayload(BaseModel):
    issue_type: Literal["BUG", "FEATURE"]
    category: str = Field(default="Other", min_length=2, max_length=80)
    description: str = Field(min_length=4, max_length=4000)
    prediction_record_id: int | None = Field(default=None, gt=0)
    entry_id: int | None = Field(default=None, gt=0)
    entry_prop_id: int | None = Field(default=None, gt=0)


class BetaInitialDecisionPayload(BaseModel):
    initial_pick: Literal["Over", "Under", "Unsure"]
    context: dict[str, Any] = Field(default_factory=dict)


class BetaBootstrapPayload(BetaUserCreatePayload):
    bootstrap_token: str = Field(min_length=8, max_length=512)
    role: Literal["ADMIN"] = "ADMIN"
