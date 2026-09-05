from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(tags=["results"])


@dataclass(frozen=True)
class ResultsDependencies:
    performance: Callable[[], dict]
    create_backup: Callable[[], dict]
    create_export: Callable[[], dict]
    backtest: Callable[[], dict]
    refresh_calibration: Callable[[], dict]
    model_health: Callable[[], dict]
    accuracy_lab: Callable[[], dict]
    data_integrity_repair: Callable[[bool], dict]


_deps_store: list[ResultsDependencies] = []


def configure_results_router(dependencies: ResultsDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> ResultsDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Results are still starting. Please try again.")
    return _deps_store[0]


DepsResults = Annotated[ResultsDependencies, Depends(get_deps)]


@router.get("/api/performance")
def performance(deps: DepsResults = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ResultsDependencies) else get_deps()
    return _deps.performance()


@router.post("/api/data/backup")
def create_database_backup(deps: DepsResults = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ResultsDependencies) else get_deps()
    try:
        return {"backup": _deps.create_backup()}
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/data/export")
def create_database_export(deps: DepsResults = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ResultsDependencies) else get_deps()
    try:
        return {"export": _deps.create_export()}
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/analytics/backtest")
def backtest(deps: DepsResults = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ResultsDependencies) else get_deps()
    return _deps.backtest()


@router.post("/api/analytics/refresh-calibration-data")
def refresh_calibration_data(deps: DepsResults = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ResultsDependencies) else get_deps()
    return _deps.refresh_calibration()


@router.get("/api/analytics/model-health")
def model_health(deps: DepsResults = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ResultsDependencies) else get_deps()
    return _deps.model_health()


@router.get("/api/analytics/accuracy-lab")
def accuracy_lab(deps: DepsResults = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ResultsDependencies) else get_deps()
    return _deps.accuracy_lab()


@router.post("/api/analytics/data-integrity-repair")
def data_integrity_repair(dry_run: bool = True, deps: DepsResults = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, ResultsDependencies) else get_deps()
    try:
        return _deps.data_integrity_repair(dry_run)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
