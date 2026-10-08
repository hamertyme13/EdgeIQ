"""Chronological changes reconstructed from immutable per-leg snapshots."""
from __future__ import annotations

import json
from datetime import UTC

from sqlalchemy import and_

from repository import database
from repository.models.leg_recommendation_snapshot_model import LegRecommendationSnapshotModel
from repository.models.provider_offer_snapshot_model import ProviderOfferSnapshotModel
from utils.entity_normalization import canonical_person_key


def _changes(previous: dict | None, current: dict) -> list[str]:
    if previous is None:
        return ["recommendation_created"]
    changes = []
    for field, event in (
        ("line", "provider_line_change"),
        ("projection", "model_projection_change"),
        ("confidence", "confidence_change"),
        ("calibrated_confidence", "calibration_change"),
        ("model_version", "model_version_change"),
        ("grade", "recommendation_grade_change"),
    ):
        if previous.get(field) != current.get(field):
            changes.append(event)
    return changes


def _probability(evidence: dict | None) -> float | None:
    if not evidence:
        return None
    calibrated = evidence.get("calibrated_confidence")
    return calibrated if calibrated is not None else evidence.get("confidence")


def _change_reasons(previous: dict | None, current: dict, changes: list[str]) -> list[str]:
    if previous is None:
        return ["First saved recommendation for this market and offer type."]
    labels = {
        "provider_line_change": ("Provider line", "line"),
        "model_projection_change": ("EdgeIQ projection", "projection"),
        "confidence_change": ("Model confidence", "confidence"),
        "calibration_change": ("Calibrated confidence", "calibrated_confidence"),
        "recommendation_grade_change": ("Grade", "grade"),
        "model_version_change": ("Model version", "model_version"),
    }
    reasons = []
    for change in changes:
        label, field = labels[change]
        reasons.append(f"{label}: {previous.get(field)} to {current.get(field)}.")
    if changes:
        reasons.append("The saved snapshots do not identify the cause of these changes.")
    return reasons


def _market_identity(offer: ProviderOfferSnapshotModel, direction: str) -> tuple[str, ...]:
    return (
        offer.provider, offer.sport,
        getattr(offer, "provider_event_id", "") or getattr(offer, "game_start", "") or offer.game,
        offer.stat, direction, getattr(offer, "offer_type", "") or "standard",
    )


def recommendation_timeline(
    *, player: str, sport: str = "", stat: str = "", game: str = "", platform: str = "", limit: int = 100,
) -> dict:
    """Read a market timeline; never modify or synthesize historical snapshots."""
    player_key = canonical_person_key(player)
    if not player_key:
        return {"events": [], "summary": "Choose a player to view recommendation history."}
    database.initialize_database()
    bound = max(1, min(limit, 200))
    with database.SessionLocal() as session:
        query = session.query(LegRecommendationSnapshotModel, ProviderOfferSnapshotModel).join(
            ProviderOfferSnapshotModel,
            and_(
                LegRecommendationSnapshotModel.offer_snapshot_id == ProviderOfferSnapshotModel.snapshot_id,
                ProviderOfferSnapshotModel.player_key == player_key,
            ),
        )
        if sport:
            query = query.filter(LegRecommendationSnapshotModel.sport == sport)
        if stat:
            query = query.filter(LegRecommendationSnapshotModel.stat == stat)
        if game:
            query = query.filter(ProviderOfferSnapshotModel.game == game)
        if platform:
            query = query.filter(ProviderOfferSnapshotModel.provider == platform)
        records = query.order_by(
            LegRecommendationSnapshotModel.id.desc(),
        ).limit(bound * 5).all()
    events = []
    previous_by_market: dict[tuple[str, ...], dict] = {}
    for snapshot, offer in reversed(records):
        evidence = json.loads(str(snapshot.evidence))
        market = _market_identity(offer, snapshot.direction)
        previous = previous_by_market.get(market)
        changes = _changes(previous, evidence)
        previous_by_market[market] = evidence
        if not changes:
            continue
        recorded = snapshot.created_at
        events.append({
            "snapshot_id": snapshot.snapshot_id,
            "previous_snapshot_id": previous.get("snapshot_id", "") if previous else "",
            "offer_snapshot_id": offer.snapshot_id,
            "player": snapshot.player,
            "sport": offer.sport,
            "stat": offer.stat,
            "game": offer.game,
            "platform": offer.provider,
            "direction": snapshot.direction,
            "created_at": recorded.replace(tzinfo=UTC).isoformat() if recorded and recorded.tzinfo is None else recorded.isoformat() if recorded else "",
            "changes": changes,
            "change_reasons": _change_reasons(previous, evidence, changes),
            "change_category": (
                "market" if "provider_line_change" in changes else
                "model" if any(change != "recommendation_created" for change in changes) else "initial"
            ),
            "offer_type": getattr(offer, "offer_type", "") or "standard",
            "market_series_key": json.dumps(market, separators=(",", ":")),
            "previous_line": previous.get("line") if previous else None,
            "line": evidence.get("line"),
            "previous_projection": previous.get("projection") if previous else None,
            "projection": evidence.get("projection"),
            "previous_probability": _probability(previous),
            "probability": _probability(evidence),
            "model_probability": evidence.get("confidence"),
            "calibrated_probability": evidence.get("calibrated_confidence"),
            "calibration_context": evidence.get("calibration_context") or {},
            "model_version": evidence.get("model_version") or getattr(snapshot, "model_version", ""),
            "previous_grade": previous.get("grade") if previous else None,
            "grade": evidence.get("grade"),
        })
        evidence["snapshot_id"] = snapshot.snapshot_id
    events = events[-bound:]
    summary = "No saved recommendation changes for this market." if not events else (
        f"{len(events)} saved recommendation state{'s' if len(events) != 1 else ''}; "
        f"latest change: {', '.join(events[-1]['changes']).replace('_', ' ')}."
    )
    return {"events": events, "summary": summary, "clv": None}
