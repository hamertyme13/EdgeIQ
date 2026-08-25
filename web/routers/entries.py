from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from web.application.entry_creation_service import EntryCreationError
from web.schemas import EntryPayload, ShareSlipPayload

router = APIRouter(tags=["entries"])


@dataclass(frozen=True)
class EntryDependencies:
    analyze: Callable[[EntryPayload], dict]
    payout_analysis: Callable[[EntryPayload], dict]
    placement_check: Callable[[EntryPayload], dict]
    platform_value_check: Callable[[EntryPayload], dict]
    handoff: Callable[[EntryPayload], dict]
    share: Callable[[ShareSlipPayload], dict]
    shared_entry: Callable[[str], dict]
    shared_entry_html: Callable[[str], str]
    place: Callable[[EntryPayload], dict]


_deps_store: list[EntryDependencies] = []


def configure_entry_router(dependencies: EntryDependencies) -> None:
    if _deps_store:
        _deps_store[0] = dependencies
    else:
        _deps_store.append(dependencies)


def get_deps() -> EntryDependencies:
    if not _deps_store:
        raise HTTPException(status_code=503, detail="Entry tools are still starting. Please try again.")
    return _deps_store[0]


DepsEntry = Annotated[EntryDependencies, Depends(get_deps)]


@router.post("/api/entries/analyze")
def analyze_entry(payload: EntryPayload, deps: DepsEntry = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    return _deps.analyze(payload)


@router.post("/api/entries/payout-analysis")
def entry_payout_analysis(payload: EntryPayload, deps: DepsEntry = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    return _deps.payout_analysis(payload)


@router.post("/api/entries/placement-check")
def placement_check(payload: EntryPayload, deps: DepsEntry = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    return _deps.placement_check(payload)


@router.post("/api/entries/platform-value-check")
def platform_value_check(payload: EntryPayload, deps: DepsEntry = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    return _deps.platform_value_check(payload)


@router.post("/api/entries/handoff")
def entry_handoff(payload: EntryPayload, deps: DepsEntry = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    return _deps.handoff(payload)


@router.post("/api/entries/share")
def share_entry(payload: ShareSlipPayload, deps: DepsEntry = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    return _deps.share(payload)


@router.get("/api/share/{share_id}")
def shared_entry(share_id: str, deps: DepsEntry = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    return _deps.shared_entry(share_id)


@router.get("/share/{share_id}")
def shared_entry_page(share_id: str, deps: DepsEntry = None) -> HTMLResponse:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    return HTMLResponse(_deps.shared_entry_html(share_id))


@router.post("/api/entries/place")
def place_entry(payload: EntryPayload, deps: DepsEntry = None) -> dict:  # type: ignore[assignment]
    _deps = deps if isinstance(deps, EntryDependencies) else get_deps()
    try:
        return _deps.place(payload)
    except EntryCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
