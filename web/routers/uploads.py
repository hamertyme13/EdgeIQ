from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from web.schemas import BettingHistoryPayload, UploadAnalyzePayload

router = APIRouter(tags=["imports"])


@dataclass(frozen=True)
class UploadDependencies:
    import_wizard: Callable[[], dict]
    analyze: Callable[[UploadAnalyzePayload], dict]
    import_history: Callable[[BettingHistoryPayload], dict]


_deps_store: list[UploadDependencies] = []


def configure_upload_router(dependencies: UploadDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> UploadDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Import tools are still starting. Please try again.")
    return _deps_store[0]


DepsUpload = Annotated[UploadDependencies, Depends(get_deps)]


@router.get("/api/import-wizard")
def import_wizard(deps: DepsUpload = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, UploadDependencies) else get_deps()
    return _deps.import_wizard()


@router.post("/api/uploads/analyze")
def analyze_uploaded_file(payload: UploadAnalyzePayload, deps: DepsUpload = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, UploadDependencies) else get_deps()
    return _deps.analyze(payload)


@router.post("/api/bets/import-history")
def import_betting_history(payload: BettingHistoryPayload, deps: DepsUpload = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, UploadDependencies) else get_deps()
    return _deps.import_history(payload)
