from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from analytics.card_probability import analyze_card_probability
from analytics.correlation import estimate_correlation_matrix
from analytics.entry_recommendation import recommendation as entry_recommendation
from analytics.pickem_payouts import payout_analysis
from analytics.prop_metrics import calculate_confidence, calculate_edge
from utils.prop_plausibility import prop_line_plausibility
from web.schemas import EntryPayload

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntryCreationError(Exception):
    status_code: int
    detail: str


def prepare_entry_analysis(entry: Any, *, payout_type: str, multiplier: float, audit_snapshot: str) -> tuple[dict, dict]:
    """Validate props, compute payout, and compute recommendation.

    This is the business logic that was previously embedded in
    ``EntryRepository.save()``.  Call this from the service layer before
    persisting so the repository only handles I/O.

    Returns ``(payout, analysis)`` ready to be passed into ``EntryRepository.save()``.
    """
    checked = [(prop, prop_line_plausibility(prop)) for prop in entry.props]
    invalid = [(prop, result) for prop, result in checked if not result.valid]
    if invalid:
        prop, validation = invalid[0]
        _log.warning(
            "Rejected implausible entry market player=%s stat=%s line=%s reason=%s",
            getattr(getattr(prop, "player", None), "name", ""),
            getattr(getattr(prop, "stat", None), "value", getattr(prop, "stat", "")),
            getattr(prop, "line", ""),
            validation.reason,
        )
        raise ValueError(f"Entry contains an invalid market: {validation.reason}")

    audit_payload: dict = {}
    try:
        audit_payload = json.loads(audit_snapshot or "{}")
    except (TypeError, ValueError):
        audit_payload = {}
    audited_payout = audit_payload.get("payout_analysis") or {}
    exact_schedule = (
        audited_payout.get("payouts")
        if audited_payout.get("source") == "exact_offer_snapshot"
        else None
    )
    payout = payout_analysis(
        [float(prop.confidence or 0.0) / 100.0 for prop in entry.props],
        entry.platform.value,
        payout_type,
        displayed_multiplier=multiplier,
        correlation_matrix=estimate_correlation_matrix(entry.props),
        exact_schedule=exact_schedule,
    )
    analysis = entry_recommendation(entry, payout)
    return payout, analysis


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
    analysis_props = []
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
        analysis_props.append({**prop.model_dump(), "confidence": confidence})
    return analyze_card_probability(
        analysis_props,
        payload.platform,
        payload.payout_type,
        displayed_multiplier=payload.multiplier,
        exact_schedule=payload.payout_schedule or None,
    )


def place_entry_payload(
    payload: EntryPayload,
    *,
    reject_combined_props: Callable[[list], None],
    loss_protection: Callable[[], dict],
    settlement_blocks: Callable[[EntryPayload], list[str]],
    generation_day_blocks: Callable[[EntryPayload], list[str]],
    requires_verified_settlement: Callable[[EntryPayload], bool],
    entry_from_payload: Callable[[EntryPayload], Any],
    analyze_entry: Callable[[Any, EntryPayload], dict],
    audit_snapshot: Callable[[Any, EntryPayload, dict, list[str]], dict],
    save_entry: Callable[..., int] | None = None,
) -> dict:
    if save_entry is None:
        from repository.repositories.entry_repository import EntryRepository as _ER
        save_entry = _ER.save
    reject_combined_props(payload.props)
    if payload.entry_mode == "real" and payload.wager <= 0:
        raise EntryCreationError(
            400,
            "Enter an amount wagered before placing the entry.",
        )
    protection = loss_protection()
    day_blocks = generation_day_blocks(payload)
    if day_blocks:
        raise EntryCreationError(409, day_blocks[0])
    verification_warnings = settlement_blocks(payload)
    if verification_warnings and requires_verified_settlement(payload):
        raise EntryCreationError(
            400,
            "Entry cannot be tracked automatically: " + verification_warnings[0],
        )
    entry = entry_from_payload(payload)
    analysis = analyze_entry(entry, payload)
    release = analysis.get("release_verdict") or {}
    if (
        payload.entry_mode == "real"
        and not payload.tracking_override
        and not release.get("paid_allowed")
    ):
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
    if hard_blocks and not payload.tracking_override:
        raise EntryCreationError(
            400,
            "Placement blocked: " + hard_blocks[0]["message"],
        )
    audit_json = json.dumps(
        audit_snapshot(entry, payload, analysis, verification_warnings)
    )
    payout, lower_analysis = prepare_entry_analysis(
        entry,
        payout_type=payload.payout_type,
        multiplier=payload.multiplier,
        audit_snapshot=audit_json,
    )
    entry_id = save_entry(
        entry,
        status="Pending",
        wager=payload.wager,
        multiplier=payload.multiplier,
        recommended_by_app=payload.recommended_by_app,
        audit_snapshot=audit_json,
        entry_mode=payload.entry_mode,
        payout_type=payload.payout_type,
        payout=payout,
        analysis=lower_analysis,
    )
    _log.info(
        "Entry persisted id=%s mode=%s platform=%s legs=%s recommended=%s",
        entry_id,
        payload.entry_mode,
        entry.platform.value,
        len(entry.props),
        payload.recommended_by_app,
    )
    return {
        "id": entry_id,
        "status": "Pending",
        "entry_mode": payload.entry_mode,
        "tracking_override": bool(payload.tracking_override),
        "loss_protection_active": bool(protection.get("active")),
        "settlement_tracking": (
            "verified"
            if not verification_warnings
            else "manual_verification_required"
        ),
        "verification_warnings": verification_warnings,
        "analysis": analysis,
    }
