"""In-app notices from saved briefing comparisons; never refresh providers here."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re

SUPPORTED = {"upgrades", "downgrades", "line_changes", "invalidated", "injury_context_changes"}
_LINE_MOVE = re.compile(r"^Line: (-?\d+(?:\.\d+)?) to (-?\d+(?:\.\d+)?)$")


def briefing_smart_alerts(changes: dict | None, settings: dict, *, now: datetime | None = None) -> list[dict]:
    if not settings.get("smart_alerts_enabled") or not isinstance(changes, dict) or not changes.get("available"):
        return []
    try:
        observed = datetime.fromisoformat(str(changes["current_at"]).replace("Z", "+00:00"))
        observed = observed.replace(tzinfo=UTC) if observed.tzinfo is None else observed.astimezone(UTC)
    except (KeyError, TypeError, ValueError):
        return []
    now = now or datetime.now(UTC)
    if not (observed <= now <= observed + timedelta(minutes=60)):
        return []
    enabled = set(settings.get("smart_alert_types") or []) & SUPPORTED
    alerts, seen = [], set()
    for event in changes.get("events") or []:
        kind = event.get("kind")
        if kind not in enabled:
            continue
        label = str(event.get("label") or "Market update")
        detail = str(event.get("detail") or "Review the current recommendation.")
        if kind == "line_changes":
            match = _LINE_MOVE.fullmatch(detail)
            if not match or abs(float(match.group(2)) - float(match.group(1))) < float(settings.get("smart_alert_line_move") or 1):
                continue
        identity = (kind, label)
        if identity in seen:
            continue
        seen.add(identity)
        alerts.append({
            "type": "Smart Alert",
            "severity": "danger" if kind == "invalidated" else "warning" if kind in {"downgrades", "injury_context_changes"} else "positive" if kind == "upgrades" else "neutral",
            "title": f"{label}: {kind.replace('_', ' ')}",
            "message": f"{detail}. From the last saved briefing comparison; recheck the live offer before placing.",
            "event_id": f"{changes['current_at']}:{kind}:{label}",
        })
        if len(alerts) >= 5:
            break
    return alerts
