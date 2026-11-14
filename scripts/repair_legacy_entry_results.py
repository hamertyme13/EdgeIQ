"""Repair a reviewed set of legacy settlements using verified local finals.

Dry-run by default. --apply writes a private JSON rollback snapshot first.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect

from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.models.final_player_stat_model import FinalPlayerStatModel
from repository.models.prediction_record_model import PredictionRecordModel
from repository.repositories.entry_repository import EntryRepository

PAPER_UNVERIFIABLE = (192, 41, 40, 39, 38, 37, 26, 25, 24, 23, 22, 21, 15)
PAID_CORRECTIONS = (504, 43, 13)
REVIEWED_IDS = (*PAPER_UNVERIFIABLE, *PAID_CORRECTIONS)


def _snapshot(row):
    return {column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs}


def _audit(entry, reason, previous):
    try:
        audit = json.loads(entry.audit_snapshot or "{}")
    except (TypeError, ValueError):
        audit = {"original_audit": entry.audit_snapshot or ""}
    if not isinstance(audit, dict):
        audit = {"original_audit": audit}
    audit.setdefault("settlement_reconciliations", []).append({
        "previous_result": previous,
        "new_result": entry.result,
        "reason": reason,
        "reconciled_at": datetime.now(UTC).isoformat(),
    })
    entry.audit_snapshot = json.dumps(audit)


def _verified_copper_final(session, *, stat, date, game):
    rows = session.query(FinalPlayerStatModel).filter_by(
        player="Kahleah Copper", sport="WNBA", stat=stat, game_date=date,
        game=game, status="played", source="espn",
    ).all()
    if len(rows) != 1:
        raise RuntimeError(f"Expected one verified Kahleah Copper {stat} final for {game} on {date}")
    return rows[0]


def run(*, apply: bool, backup_dir: Path) -> dict:
    with SessionLocal() as session:
        entries = {entry.id: entry for entry in session.query(EntryModel).filter(EntryModel.id.in_(REVIEWED_IDS)).all()}
        if set(entries) != set(REVIEWED_IDS):
            raise RuntimeError("The reviewed entry set changed; no repair was applied.")
        props = session.query(EntryPropModel).filter(EntryPropModel.entry_id.in_(REVIEWED_IDS)).order_by(EntryPropModel.id).all()
        by_entry = {entry_id: [prop for prop in props if prop.entry_id == entry_id] for entry_id in REVIEWED_IDS}
        predictions = session.query(PredictionRecordModel).filter(PredictionRecordModel.entry_id.in_(REVIEWED_IDS)).all()
        for entry_id in PAPER_UNVERIFIABLE:
            entry = entries[entry_id]
            if (entry.entry_mode, entry.status, entry.result) != ("paper", "Settled", "Win"):
                raise RuntimeError(f"Paper entry {entry_id} changed; no repair was applied.")
            if not any(prop.final_source == "projection_estimate" or prop.final_result == "Unknown" for prop in by_entry[entry_id]):
                raise RuntimeError(f"Paper entry {entry_id} is no longer unverified.")
        for entry_id, expected in ((504, "Win"), (43, "Win"), (13, "Loss")):
            entry = entries[entry_id]
            if (entry.entry_mode, entry.status, entry.result, entry.payout_type) != ("real", "Settled", expected, "standard"):
                raise RuntimeError(f"Paid entry {entry_id} changed; no repair was applied.")
        if not any(p.final_result == "Loss" and p.final_source == "espn" for p in by_entry[504]):
            raise RuntimeError("Entry 504 lacks its verified losing legs.")
        aliases = (
            (43, 128, "Kaleah Copper", "Rebounds", "2026-07-13", "PHX@MIN", 3.0),
            (13, 40, "Kahleah Cooper", "Points", "2026-07-11", "PHX@LV", 9.0),
        )
        finals = {}
        for entry_id, prop_id, name, stat, date, game, actual in aliases:
            prop = next((p for p in by_entry[entry_id] if p.id == prop_id), None)
            if prop is None or (prop.player_name, prop.stat, prop.final_result, prop.actual) != (name, stat, "Unknown", None):
                raise RuntimeError(f"Leg {prop_id} changed; no repair was applied.")
            final = _verified_copper_final(session, stat=stat, date=date, game=game)
            if final.actual != actual:
                raise RuntimeError(f"Verified final for leg {prop_id} changed.")
            finals[prop_id] = final
        summary = {"paid_outcome_corrections": [504, 43], "paid_leg_repairs": [128, 40],
                   "paper_exclusions": list(PAPER_UNVERIFIABLE), "backup": None, "applied": False}
        if not apply:
            return summary
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"edgeiq-entry-repair-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"entries": [_snapshot(e) for e in entries.values()],
                       "props": [_snapshot(p) for p in props],
                       "predictions": [_snapshot(p) for p in predictions]}, stream, default=str)
        summary["backup"] = str(backup)
        for entry_id in PAPER_UNVERIFIABLE:
            entry = entries[entry_id]
            previous = entry.result
            entry.status = "Excluded"
            entry.result = "Unverifiable"
            entry.profit = 0.0
            _audit(entry, "Legacy paper card contained projection-estimated or unknown finals; removed from accuracy and calibration.", previous)
        for record in predictions:
            if record.entry_id in PAPER_UNVERIFIABLE:
                record.legacy_quarantined = True
        for entry_id, prop_id, *_ in aliases:
            prop = next(p for p in by_entry[entry_id] if p.id == prop_id)
            final = finals[prop_id]
            prop.actual = final.actual
            prop.final_result = "Loss"
            prop.final_source = "espn"
            prop.final_status = "played"
            for record in predictions:
                if record.entry_prop_id == prop_id:
                    record.outcome = "Loss"
                    record.actual = final.actual
                    record.outcome_source = "espn"
                    record.settled_at = datetime.now(UTC)
            _audit(entries[entry_id], f"Verified ESPN {final.game_date} {final.game}: {prop.player_name} matched Kahleah Copper {final.stat} {final.actual}; original name retained.", entries[entry_id].result)
        for entry_id in (504, 43):
            entry = entries[entry_id]
            previous = entry.result
            entry.result = "Loss"
            entry.profit = -float(entry.wager)
            _audit(entry, "Standard card has a verified ESPN losing leg; corrected result and wager loss.", previous)
        session.commit()
        summary["applied"] = True
    # Keep the legacy bankroll/history mirror aligned with the corrected paid cards.
    with SessionLocal() as session:
        paid_payloads = [EntryRepository._entry_dict(session, session.get(EntryModel, i)) for i in PAID_CORRECTIONS]
    for payload in paid_payloads:
        EntryRepository._sync_entry_to_bet_history(payload)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=Path("/private/tmp"))
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply, backup_dir=args.backup_dir), indent=2))
