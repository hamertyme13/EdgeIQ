"""Read-only integrity audit of placed entries and their final-result legs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.models.shadow_prediction_model import ShadowPredictionModel

_FINAL_LEGS = {"Win", "Loss", "Push", "DNP"}


def entry_flags(entry: dict, legs: list[dict], *, now: datetime) -> list[str]:
    """Flag contradictions without interpreting flex or unresolved legs as losses."""
    flags = []
    status = str(entry.get("status") or "")
    result = str(entry.get("result") or "")
    leg_results = [str(leg.get("final_result") or "") for leg in legs]
    all_final = bool(legs) and all(value in _FINAL_LEGS for value in leg_results)
    if status == "Pending" and all_final:
        flags.append("pending_with_all_leg_results")
    if status == "Settled":
        if not legs:
            flags.append("settled_without_legs")
        if result not in _FINAL_LEGS:
            flags.append("settled_without_card_result")
        unresolved = any(value not in _FINAL_LEGS for value in leg_results)
        known_standard_loss = (
            str(entry.get("payout_type") or "standard") != "flex"
            and result == "Loss" and "Loss" in leg_results
        )
        if unresolved and not known_standard_loss:
            flags.append("settled_with_unresolved_leg")
        if all_final and all(value == "Win" for value in leg_results) and result != "Win":
            flags.append("all_winning_legs_but_card_not_win")
        if (all_final and str(entry.get("payout_type") or "standard") != "flex"
                and "Loss" in leg_results and result == "Win"):
            flags.append("standard_card_win_with_losing_leg")
    placed = entry.get("placed_at")
    if status == "Pending" and isinstance(placed, datetime):
        placed = placed.replace(tzinfo=UTC) if placed.tzinfo is None else placed.astimezone(UTC)
        if placed < now - timedelta(days=2):
            flags.append("pending_more_than_two_days_since_placement")
    return flags


def audit(*, example_limit: int = 20) -> dict:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        entries = session.query(EntryModel).all()
        props = session.query(EntryPropModel).all()
        shadow = session.query(ShadowPredictionModel.status, ShadowPredictionModel.outcome_source).filter(
            ShadowPredictionModel.model_version.like("nba-points-board/%")
        ).all()
    by_entry: dict[int, list[dict]] = defaultdict(list)
    for prop in props:
        by_entry[prop.entry_id].append({"final_result": prop.final_result})
    flags: Counter[str] = Counter()
    examples: dict[str, list[int]] = defaultdict(list)
    by_mode_status = Counter()
    by_mode_result = Counter()
    paid_wager = 0.0
    paid_profit = 0.0
    for row in entries:
        by_mode_status[(row.entry_mode, row.status)] += 1
        if row.status == "Settled":
            by_mode_result[(row.entry_mode, row.result)] += 1
            if row.entry_mode == "real":
                paid_wager += float(row.wager or 0)
                paid_profit += float(row.profit or 0)
        entry = {"status": row.status, "result": row.result, "payout_type": row.payout_type,
                 "placed_at": row.placed_at}
        for flag in entry_flags(entry, by_entry.get(row.id, []), now=now):
            flags[flag] += 1
            if len(examples[flag]) < example_limit:
                examples[flag].append(row.id)
    shadow_status = Counter((row.status, row.outcome_source or "") for row in shadow)
    return {
        "entries": len(entries), "legs": len(props),
        "by_mode_status": {f"{mode}:{status}": count for (mode, status), count in sorted(by_mode_status.items())},
        "settled_by_mode_result": {f"{mode}:{result}": count for (mode, result), count in sorted(by_mode_result.items())},
        "paid_settled": {
            "wagered": round(paid_wager, 2), "profit": round(paid_profit, 2),
            "roi_percent": round(100 * paid_profit / paid_wager, 1) if paid_wager else None,
        },
        "review_flags": dict(sorted(flags.items())),
        "example_entry_ids": dict(sorted(examples.items())),
        "nba_points_shadow_status": {f"{status}:{source or 'unspecified'}": count
                                     for (status, source), count in sorted(shadow_status.items())},
        "note": "Read-only review flags. Flex payouts and missing finals require separate verification before correction.",
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
