from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return a UTC timestamp stored as naive for SQLite DateTime compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
