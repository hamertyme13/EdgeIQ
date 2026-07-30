from typing import Literal

from pydantic import BaseModel, Field


class BankrollPayload(BaseModel):
    amount: float = Field(gt=0)


class BankrollTransactionPayload(BaseModel):
    transaction_type: Literal["Deposit", "Withdrawal"]
    amount: float = Field(gt=0)
    note: str = ""


class BankrollStrategyPayload(BaseModel):
    mode: Literal["flat", "conservative", "balanced", "aggressive", "kelly", "paper"] = "balanced"
    unit_size: float = Field(default=10.0, ge=0)
    max_wager_pct: float = Field(default=5.0, ge=0.1, le=100)
    max_open_exposure_pct: float = Field(default=15.0, ge=0.1, le=100)
    stop_loss_pct: float = Field(default=12.0, ge=0.1, le=100)
    paper_first: bool = False
