from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from web.schemas import FinalStatsPayload, SettlePayload

router = APIRouter(tags=["settlement"])


@dataclass(frozen=True)
class SettlementDependencies:
    grading_report: Callable[[bool], dict]
    settlement_audit: Callable[[int], dict]
    pending_entries: Callable[[], dict]
    entry_progress: Callable[[bool, bool, bool], dict]
    settle_entry: Callable[[int, SettlePayload], dict]
    auto_check: Callable[[bool, bool], dict]
    backfill_final_stats: Callable[[bool], dict]
    recheck_final_stats: Callable[[bool], dict]
    classify_default_wagers: Callable[[], dict]
    import_final_stats: Callable[[FinalStatsPayload], dict]


_dependencies: SettlementDependencies | None = None


def configure_settlement_router(dependencies: SettlementDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> SettlementDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Settlement tracking is still starting. Please try again.")
    return _dependencies


@router.get("/api/entries/grading-report")
def grading_report(compact: bool = False) -> dict:
    return _deps().grading_report(compact)


@router.get("/api/entries/settlement-audit")
def settlement_audit(limit: int = 100) -> dict:
    return _deps().settlement_audit(limit)


@router.get("/api/entries/pending")
def pending_entries() -> dict:
    return _deps().pending_entries()


@router.get("/api/entries/progress")
def entry_progress(
    auto_check: bool = False,
    refresh_providers: bool = False,
    market_detail: bool = True,
) -> dict:
    return _deps().entry_progress(auto_check, refresh_providers, market_detail)


@router.post("/api/entries/{entry_id}/settle")
def settle_entry(entry_id: int, payload: SettlePayload) -> dict:
    return _deps().settle_entry(entry_id, payload)


@router.post("/api/entries/auto-check")
def auto_check_entries(
    allow_estimates: bool = False,
    refresh_providers: bool = True,
) -> dict:
    return _deps().auto_check(allow_estimates, refresh_providers)


@router.post("/api/entries/backfill-final-stats")
def backfill_entry_final_stats(allow_estimates: bool = True) -> dict:
    return _deps().backfill_final_stats(allow_estimates)


@router.post("/api/entries/recheck-final-stats")
def recheck_entry_final_stats(allow_estimates: bool = False) -> dict:
    return _deps().recheck_final_stats(allow_estimates)


@router.post("/api/entries/classify-default-wagers")
def classify_default_entry_wagers() -> dict:
    return _deps().classify_default_wagers()


@router.post("/api/final-stats/import")
def import_final_stats_endpoint(payload: FinalStatsPayload) -> dict:
    return _deps().import_final_stats(payload)
