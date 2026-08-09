from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException
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


_dependencies: EntryDependencies | None = None


def configure_entry_router(dependencies: EntryDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> EntryDependencies:
    if _dependencies is None:
        raise HTTPException(status_code=503, detail="Entry tools are still starting. Please try again.")
    return _dependencies


@router.post("/api/entries/analyze")
def analyze_entry(payload: EntryPayload) -> dict:
    return _deps().analyze(payload)


@router.post("/api/entries/payout-analysis")
def entry_payout_analysis(payload: EntryPayload) -> dict:
    return _deps().payout_analysis(payload)


@router.post("/api/entries/placement-check")
def placement_check(payload: EntryPayload) -> dict:
    return _deps().placement_check(payload)


@router.post("/api/entries/platform-value-check")
def platform_value_check(payload: EntryPayload) -> dict:
    return _deps().platform_value_check(payload)


@router.post("/api/entries/handoff")
def entry_handoff(payload: EntryPayload) -> dict:
    return _deps().handoff(payload)


@router.post("/api/entries/share")
def share_entry(payload: ShareSlipPayload) -> dict:
    return _deps().share(payload)


@router.get("/api/share/{share_id}")
def shared_entry(share_id: str) -> dict:
    return _deps().shared_entry(share_id)


@router.get("/share/{share_id}")
def shared_entry_page(share_id: str) -> HTMLResponse:
    return HTMLResponse(_deps().shared_entry_html(share_id))


@router.post("/api/entries/place")
def place_entry(payload: EntryPayload) -> dict:
    try:
        return _deps().place(payload)
    except EntryCreationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
