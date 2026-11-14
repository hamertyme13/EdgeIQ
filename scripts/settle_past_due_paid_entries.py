"""Settle reviewed, past-due paid standard cards with verified losing legs.

Missing leg finals remain unknown. Dry-run by default; --apply backs up the
original entry and leg rows before changing financial history.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect

from repository.database import SessionLocal
from repository.models.entry_model import EntryModel
from repository.models.entry_prop_model import EntryPropModel
from repository.models.prediction_record_model import PredictionRecordModel
from repository.repositories.entry_repository import EntryRepository

REVIEWED_IDS = (1419, 2056)


def _snapshot(row):
    return {column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs}


def run(*, apply: bool, backup_dir: Path) -> dict:
    with SessionLocal() as session:
        entries = session.query(EntryModel).filter(EntryModel.id.in_(REVIEWED_IDS)).all()
        if {entry.id for entry in entries} != set(REVIEWED_IDS):
            raise RuntimeError("Reviewed paid entries changed; no settlement was applied.")
        props = session.query(EntryPropModel).filter(EntryPropModel.entry_id.in_(REVIEWED_IDS)).all()
        predictions = session.query(PredictionRecordModel).filter(PredictionRecordModel.entry_id.in_(REVIEWED_IDS)).all()
        now = datetime.now(UTC)
        for entry in entries:
            placed = entry.placed_at
            if placed is None:
                raise RuntimeError(f"Entry {entry.id} has no placement time.")
            placed = placed.replace(tzinfo=UTC) if placed.tzinfo is None else placed.astimezone(UTC)
            legs = [prop for prop in props if prop.entry_id == entry.id]
            verified = [prop for prop in legs if prop.final_status == "played" and prop.actual is not None
                        and prop.final_source not in {"", "projection_estimate"}]
            if (entry.status, entry.entry_mode, entry.payout_type) != ("Pending", "real", "standard"):
                raise RuntimeError(f"Entry {entry.id} is no longer a pending paid standard card.")
            if now - placed < timedelta(hours=48) or len(verified) < 2:
                raise RuntimeError(f"Entry {entry.id} is not safely past due with verified legs.")
            if not any(prop.final_result == "Loss" for prop in verified):
                raise RuntimeError(f"Entry {entry.id} has no verified losing leg.")
            if any(prop.final_result == "DNP" for prop in legs):
                raise RuntimeError(f"Entry {entry.id} requires DNP payout review.")
        result = {"reviewed": list(REVIEWED_IDS), "settled": [], "backup": None, "applied": False}
        if not apply:
            return result
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / f"edgeiq-pending-paid-{now:%Y%m%dT%H%M%SZ}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"entries": [_snapshot(row) for row in entries],
                       "props": [_snapshot(row) for row in props],
                       "predictions": [_snapshot(row) for row in predictions]}, stream, default=str)
        result["backup"] = str(path)
    for entry_id in REVIEWED_IDS:
        EntryRepository.settle(
            entry_id, "Loss",
            correction_reason=(
                "Past-due paid standard card: multiple played legs have provider-verified losses. "
                "The unresolved leg remains unknown and was not used for calibration."
            ),
        )
        result["settled"].append(entry_id)
    result["applied"] = True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=Path("/private/tmp"))
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply, backup_dir=args.backup_dir), indent=2))
