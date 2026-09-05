from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

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


_deps_store: list[BankrollDependencies] = []


def configure_bankroll_router(dependencies: BankrollDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> BankrollDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Bankroll tools are still starting. Please try again.")
    return _deps_store[0]


DepsBankroll = Annotated[BankrollDependencies, Depends(get_deps)]


@router.post("/api/settings/bankroll")
def update_bankroll(payload: BankrollPayload, deps: DepsBankroll = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, BankrollDependencies) else get_deps()
    return _deps.update_bankroll(payload)


@router.get("/api/bankroll/transactions")
def bankroll_transactions(deps: DepsBankroll = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, BankrollDependencies) else get_deps()
    return _deps.transactions()


@router.post("/api/bankroll/transactions")
def save_bankroll_transaction(payload: BankrollTransactionPayload, deps: DepsBankroll = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, BankrollDependencies) else get_deps()
    return _deps.save_transaction(payload)


@router.get("/api/settings/bankroll-strategy")
def bankroll_strategy(deps: DepsBankroll = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, BankrollDependencies) else get_deps()
    return _deps.strategy()


@router.post("/api/settings/bankroll-strategy")
def update_bankroll_strategy(payload: BankrollStrategyPayload, deps: DepsBankroll = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, BankrollDependencies) else get_deps()
    return _deps.update_strategy(payload)


@router.get("/api/loss-protection")
def loss_protection(deps: DepsBankroll = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, BankrollDependencies) else get_deps()
    return _deps.loss_protection()


@router.post("/api/loss-protection")
def update_loss_protection(payload: LossProtectionSettingPayload, deps: DepsBankroll = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, BankrollDependencies) else get_deps()
    return _deps.update_loss_protection(payload)


@router.get("/api/analytics/loss-review")
def loss_review(limit: int = 10, deps: DepsBankroll = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, BankrollDependencies) else get_deps()
    return _deps.loss_review(limit)
