from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from web.schemas import BettingHistoryPayload, UploadAnalyzePayload

router = APIRouter(tags=["imports"])


@dataclass(frozen=True)
class UploadDependencies:
    import_wizard: Callable[[], dict]
    analyze: Callable[[UploadAnalyzePayload], dict]
    import_history: Callable[[BettingHistoryPayload], dict]


_dependencies: UploadDependencies | None = None


def configure_upload_router(dependencies: UploadDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> UploadDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Import tools are still starting. Please try again.")
    return _dependencies


@router.get("/api/import-wizard")
def import_wizard() -> dict:
    return _deps().import_wizard()


@router.post("/api/uploads/analyze")
def analyze_uploaded_file(payload: UploadAnalyzePayload) -> dict:
    return _deps().analyze(payload)


@router.post("/api/bets/import-history")
def import_betting_history(payload: BettingHistoryPayload) -> dict:
    return _deps().import_history(payload)
