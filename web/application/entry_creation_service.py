from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from analytics.correlation import estimate_correlation_matrix
from analytics.pickem_payouts import payout_analysis
from analytics.prop_metrics import calculate_confidence, calculate_edge
from repository.repositories.entry_repository import EntryRepository
from web.schemas import EntryPayload


@dataclass(frozen=True)
class EntryCreationError(Exception):
    status_code: int
    detail: str


def validated_call(
    props: list,
    reject_combined_props: Callable[[list], None],
    operation: Callable[[], dict],
) -> dict:
    reject_combined_props(props)
    return operation()


def analyze_entry_payload(
    payload: EntryPayload,
    reject_combined_props: Callable[[list], None],
    entry_from_payload: Callable[[EntryPayload], Any],
    analyze_entry: Callable[[Any, EntryPayload], dict],
) -> dict:
    reject_combined_props(payload.props)
    entry = entry_from_payload(payload)
    return analyze_entry(entry, payload)


def payout_analysis_payload(
    payload: EntryPayload,
    reject_combined_props: Callable[[list], None],
    normalize_direction: Callable[[str], str],
) -> dict:
    reject_combined_props(payload.props)
    probabilities = []
    for prop in payload.props:
        if prop.confidence is not None:
            confidence = float(prop.confidence)
        elif prop.projection is not None:
            edge = calculate_edge(prop.line, prop.projection)
            if normalize_direction(prop.direction or "Over") == "Under":
                edge *= -1
            confidence = calculate_confidence(edge, prop.stat, prop.sport)
        else:
            confidence = 50.0
        probabilities.append(confidence / 100.0)
    return payout_analysis(
        probabilities,
        payload.platform,
        payload.payout_type,
        displayed_multiplier=payload.multiplier,
        correlation_matrix=estimate_correlation_matrix(payload.props),
        exact_schedule=payload.payout_schedule or None,
    )


def place_entry_payload(
    payload: EntryPayload,
    *,
    reject_combined_props: Callable[[list], None],
    loss_protection: Callable[[], dict],
    settlement_blocks: Callable[[EntryPayload], list[str]],
    requires_verified_settlement: Callable[[EntryPayload], bool],
    entry_from_payload: Callable[[EntryPayload], Any],
    analyze_entry: Callable[[Any, EntryPayload], dict],
    audit_snapshot: Callable[[Any, EntryPayload, dict, list[str]], dict],
    dashboard: Callable[[], dict],
) -> dict:
    reject_combined_props(payload.props)
    if payload.entry_mode == "real" and payload.wager <= 0:
        raise EntryCreationError(
            400,
            "Enter an amount wagered before placing the entry.",
        )
    if payload.entry_mode == "real" and loss_protection()["active"]:
        raise EntryCreationError(
            409,
            "Loss Protection is active. Real-money entries are not allowed in this mode. "
            "Save this as a paper entry and wait for tracked performance to recover.",
        )
    verification_warnings = settlement_blocks(payload)
    if verification_warnings and requires_verified_settlement(payload):
        raise EntryCreationError(
            400,
            "Entry cannot be tracked automatically: " + verification_warnings[0],
        )
    entry = entry_from_payload(payload)
    analysis = analyze_entry(entry, payload)
    release = analysis.get("release_verdict") or {}
    if payload.entry_mode == "real" and not release.get("paid_allowed"):
        reason = (
            release.get("reasons")
            or ["This entry did not clear the paid-entry release checks."]
        )[0]
        raise EntryCreationError(400, f"Paid entry blocked: {reason}")
    hard_blocks = [
        guard
        for guard in analysis.get("risk_guardrails", [])
        if guard.get("severity") == "danger"
    ]
    if hard_blocks:
        raise EntryCreationError(
            400,
            "Placement blocked: " + hard_blocks[0]["message"],
        )
    entry_id = EntryRepository.save(
        entry,
        status="Pending",
        wager=payload.wager,
        multiplier=payload.multiplier,
        recommended_by_app=payload.recommended_by_app,
        audit_snapshot=json.dumps(
            audit_snapshot(entry, payload, analysis, verification_warnings)
        ),
        entry_mode=payload.entry_mode,
        payout_type=payload.payout_type,
    )
    return {
        "id": entry_id,
        "status": "Pending",
        "entry_mode": payload.entry_mode,
        "settlement_tracking": (
            "verified"
            if not verification_warnings
            else "manual_verification_required"
        ),
        "verification_warnings": verification_warnings,
        "analysis": analysis,
        "dashboard": dashboard(),
    }
