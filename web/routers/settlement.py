from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from repository.repositories.product_experience_repository import ProductExperienceRepository
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
    recheck_final_stats_preview: Callable[[], dict]
    recheck_final_stats: Callable[[bool], dict]
    classify_default_wagers: Callable[[], dict]
    import_final_stats: Callable[[FinalStatsPayload], dict]


_deps_store: list[SettlementDependencies] = []


def configure_settlement_router(dependencies: SettlementDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> SettlementDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Settlement tracking is still starting. Please try again.")
    return _deps_store[0]


DepsSettlement = Annotated[SettlementDependencies, Depends(get_deps)]


@router.get("/api/entries/grading-report")
def grading_report(compact: bool = False, deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.grading_report(compact)


@router.get("/api/entries/settlement-audit")
def settlement_audit(limit: int = 100, deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.settlement_audit(limit)


@router.get("/api/entries/pending")
def pending_entries(deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.pending_entries()


@router.get("/api/entries/progress")
def entry_progress(
    auto_check: bool = False,
    refresh_providers: bool = False,
    market_detail: bool = True,
    deps: DepsSettlement = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.entry_progress(auto_check, refresh_providers, market_detail)


@router.post("/api/entries/{entry_id}/settle")
def settle_entry(entry_id: int, payload: SettlePayload, deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    result = _deps.settle_entry(entry_id, payload)
    ProductExperienceRepository.record_event(
        "entry_settled",
        "entry",
        str(entry_id),
        {"result": payload.result},
    )
    return result


@router.post("/api/entries/auto-check")
def auto_check_entries(
    allow_estimates: bool = False,
    refresh_providers: bool = True,
    deps: DepsSettlement = None,  # type: ignore[assignment]
) -> dict:
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.auto_check(allow_estimates, refresh_providers)


@router.post("/api/entries/backfill-final-stats")
def backfill_entry_final_stats(allow_estimates: bool = True, deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.backfill_final_stats(allow_estimates)


@router.get("/api/entries/recheck-final-stats/preview")
def preview_entry_final_stats_recheck(deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.recheck_final_stats_preview()


@router.post("/api/entries/recheck-final-stats")
def recheck_entry_final_stats(allow_estimates: bool = False, deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.recheck_final_stats(allow_estimates)


@router.post("/api/entries/classify-default-wagers")
def classify_default_entry_wagers(deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.classify_default_wagers()


@router.post("/api/final-stats/import")
def import_final_stats_endpoint(payload: FinalStatsPayload, deps: DepsSettlement = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, SettlementDependencies) else get_deps()
    return _deps.import_final_stats(payload)
