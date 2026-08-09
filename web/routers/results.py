from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

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


_dependencies: ResultsDependencies | None = None


def configure_results_router(dependencies: ResultsDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> ResultsDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Results are still starting. Please try again.")
    return _dependencies


@router.get("/api/performance")
def performance() -> dict:
    return _deps().performance()


@router.post("/api/data/backup")
def create_database_backup() -> dict:
    try:
        return {"backup": _deps().create_backup()}
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/data/export")
def create_database_export() -> dict:
    try:
        return {"export": _deps().create_export()}
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/analytics/backtest")
def backtest() -> dict:
    return _deps().backtest()


@router.post("/api/analytics/refresh-calibration-data")
def refresh_calibration_data() -> dict:
    return _deps().refresh_calibration()


@router.get("/api/analytics/model-health")
def model_health() -> dict:
    return _deps().model_health()


@router.get("/api/analytics/accuracy-lab")
def accuracy_lab() -> dict:
    return _deps().accuracy_lab()


@router.post("/api/analytics/data-integrity-repair")
def data_integrity_repair(dry_run: bool = True) -> dict:
    try:
        return _deps().data_integrity_repair(dry_run)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
