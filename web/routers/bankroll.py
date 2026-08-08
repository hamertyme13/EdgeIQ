from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from web.schemas import (
    BankrollPayload,
    BankrollStrategyPayload,
    BankrollTransactionPayload,
    LossProtectionSettingPayload,
)

router = APIRouter(tags=["bankroll"])


@dataclass(frozen=True)
class BankrollDependencies:
    update_bankroll: Callable[[BankrollPayload], dict]
    transactions: Callable[[], dict]
    save_transaction: Callable[[BankrollTransactionPayload], dict]
    strategy: Callable[[], dict]
    update_strategy: Callable[[BankrollStrategyPayload], dict]
    loss_protection: Callable[[], dict]
    update_loss_protection: Callable[[LossProtectionSettingPayload], dict]
    loss_review: Callable[[int], dict]


_dependencies: BankrollDependencies | None = None


def configure_bankroll_router(dependencies: BankrollDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> BankrollDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Bankroll tools are still starting. Please try again.")
    return _dependencies


@router.post("/api/settings/bankroll")
def update_bankroll(payload: BankrollPayload) -> dict:
    return _deps().update_bankroll(payload)


@router.get("/api/bankroll/transactions")
def bankroll_transactions() -> dict:
    return _deps().transactions()


@router.post("/api/bankroll/transactions")
def save_bankroll_transaction(payload: BankrollTransactionPayload) -> dict:
    return _deps().save_transaction(payload)


@router.get("/api/settings/bankroll-strategy")
def bankroll_strategy() -> dict:
    return _deps().strategy()


@router.post("/api/settings/bankroll-strategy")
def update_bankroll_strategy(payload: BankrollStrategyPayload) -> dict:
    return _deps().update_strategy(payload)


@router.get("/api/loss-protection")
def loss_protection() -> dict:
    return _deps().loss_protection()


@router.post("/api/loss-protection")
def update_loss_protection(payload: LossProtectionSettingPayload) -> dict:
    return _deps().update_loss_protection(payload)


@router.get("/api/analytics/loss-review")
def loss_review(limit: int = 10) -> dict:
    return _deps().loss_review(limit)
