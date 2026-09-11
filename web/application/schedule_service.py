from __future__ import annotations

from datetime import datetime, timedelta


def elapsed_job_due(last_run: str, now: datetime, interval_minutes: int) -> bool:
    previous = _parse(last_run, now)
    return previous is None or (now - previous).total_seconds() >= interval_minutes * 60


def scheduled_job_due(rule: str, last_run: str, now: datetime) -> bool:
    due_at = latest_scheduled_occurrence(rule, now)
    if due_at is None:
        return False
    previous = _parse(last_run, now)
    return previous is None or previous < due_at


def scheduled_job_overdue(rule: str, last_run: str, now: datetime) -> bool:
    if rule.startswith("*/"):
        try:
            return elapsed_job_due(last_run, now, max(1, int(rule[2:])) * 2)
        except ValueError:
            return False
    return scheduled_job_due(rule, last_run, now)


def latest_scheduled_occurrence(rule: str, now: datetime) -> datetime | None:
    if not rule or rule.startswith("*/"):
        return None
    try:
        hour, minute = (int(part) for part in rule.split(":", 1))
        today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (TypeError, ValueError):
        return None
    return today if now >= today else today - timedelta(days=1)


def _parse(value: str, now: datetime) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        return parsed.astimezone(now.tzinfo)
    except (TypeError, ValueError):
        return None
