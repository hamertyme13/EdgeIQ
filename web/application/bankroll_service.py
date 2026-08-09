from __future__ import annotations

from collections.abc import Callable

from repository.repositories.bankroll_transaction_repository import BankrollTransactionRepository


def update_bankroll_payload(
    amount: float,
    *,
    set_starting_bankroll: Callable[[float], object],
    dashboard: Callable[[float], dict],
) -> dict:
    set_starting_bankroll(amount)
    return dashboard(amount)


def bankroll_transactions_payload(dashboard: Callable[[], dict]) -> dict:
    return {
        "summary": BankrollTransactionRepository.summary(),
        "transactions": BankrollTransactionRepository.all(),
        "dashboard": dashboard(),
    }


def save_bankroll_transaction_payload(
    transaction_type: str,
    amount: float,
    note: str,
    *,
    dashboard: Callable[[], dict],
) -> dict:
    transaction = BankrollTransactionRepository.save(transaction_type, amount, note)
    return {
        "transaction": transaction,
        "summary": BankrollTransactionRepository.summary(),
        "dashboard": dashboard(),
    }


def update_bankroll_strategy_payload(
    strategy: dict,
    *,
    save_setting: Callable[[str, str], object],
    serialize: Callable[[dict], str],
    load_strategy: Callable[[], dict],
) -> dict:
    save_setting("bankroll_strategy", serialize(strategy))
    return {"strategy": load_strategy()}


def update_loss_protection_payload(
    enabled: bool,
    *,
    save_setting: Callable[[str, str], object],
    load_protection: Callable[[], dict],
) -> dict:
    save_setting("loss_protection_enabled", "true" if enabled else "false")
    return load_protection()
