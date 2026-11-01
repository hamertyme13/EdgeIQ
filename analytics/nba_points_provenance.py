"""Import-time provenance for locked NBA Points history snapshots."""

from __future__ import annotations

from datetime import UTC, datetime


def history_import_provenance(rows: list[dict], locked_at: str) -> dict:
    lock = datetime.fromisoformat(locked_at.replace("Z", "+00:00"))
    lock = lock.replace(tzinfo=UTC) if lock.tzinfo is None else lock.astimezone(UTC)
    missing = invalid = after_lock = 0
    latest: datetime | None = None
    for row in rows:
        value = row.get("imported_at")
        if not value:
            missing += 1
            continue
        try:
            import_text = str(value)
            if "T" not in import_text and " " not in import_text:
                raise ValueError("Import time lacks a clock value")
            imported = datetime.fromisoformat(import_text.replace("Z", "+00:00"))
            imported = imported.replace(tzinfo=UTC) if imported.tzinfo is None else imported.astimezone(UTC)
        except ValueError:
            invalid += 1
            continue
        latest = max(latest, imported) if latest else imported
        after_lock += imported > lock
    status = (
        "imported_after_lock" if after_lock else
        "invalid_import_time" if invalid else
        "timestamp_unverified" if missing else
        "verified"
    )
    return {
        "status": status,
        "rows": len(rows),
        "missing_import_time": missing,
        "invalid_import_time": invalid,
        "imported_after_lock": after_lock,
        "latest_imported_at": latest.isoformat() if latest else None,
    }
