from __future__ import annotations

import math
from copy import deepcopy
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from web.application.opportunity_presentation import scored_opportunities


def select_daily_snapshot(feed: dict, platform: str, sport: str | None,
                          *, now: datetime | None = None) -> dict:
    """Reuse a matching recent snapshot; never start another recommendation scan."""
    current = now or datetime.now(UTC)
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
    briefing = feed.get("daily_briefing") or {}
    unavailable = {"available": False, "briefing": {},
                   "message": "Refresh Today for this sport and provider to create a shared recommendation snapshot."}
    if not briefing.get("recommendation_snapshot_id"):
        return unavailable
    if str(briefing.get("sport") or "All Sports").upper() != str(sport or "All Sports").upper():
        return unavailable
    requested = briefing.get("requested_platform") or briefing.get("platform")
    if platform not in {requested, briefing.get("platform")}:
        return unavailable
    try:
        captured = datetime.fromisoformat(str(briefing.get("as_of") or "").replace("Z", "+00:00"))
    except ValueError:
        return unavailable
    if captured.tzinfo is None:
        return unavailable
    age = (current - captured).total_seconds()
    eastern = ZoneInfo("America/New_York")
    if age < 0 or age > 1800 or captured.astimezone(eastern).date() != current.astimezone(eastern).date():
        return {**unavailable, "message": "The shared recommendation snapshot has expired. Refresh Today before reviewing current opportunities."}
    return {"available": True, "briefing": deepcopy(briefing),
            "message": "Using the same recommendation snapshot as Today.",
            "snapshot_id": briefing["recommendation_snapshot_id"]}


def shared_opportunity_feed(feed: dict, platform: str, sport: str | None,
                            min_ev: float | None, limit: int, odds: int,
                            *, now: datetime | None = None) -> dict:
    selected = select_daily_snapshot(feed, platform, sport, now=now)
    briefing = selected["briefing"]
    rows = briefing.get("top_opportunities") or []
    accepted = []
    unverified = 0
    for row in rows:
        value = row.get("expected_value")
        verified = row.get("expected_value_verified") is True
        try:
            ev = float(value) if value is not None else None
        except (TypeError, ValueError):
            ev = None
        verified = verified and ev is not None and math.isfinite(ev)
        if not verified:
            unverified += 1
        if min_ev is not None and (not verified or ev is None or ev < min_ev):
            continue
        accepted.append(row)
    payload = {
        "feed": {"id": "edgeiq-shared-today-v1", "canonical": True,
                 "purpose": "Read-only view of Today's recommendation snapshot."},
        "as_of": briefing.get("as_of"), "platform": briefing.get("platform") or platform,
        "requested_platform": platform, "sport": sport or "All Sports",
        "available": selected["available"], "message": selected["message"],
        "recommendation_snapshot_id": selected.get("snapshot_id"),
        "model_version": briefing.get("model_version"),
        "opportunities": accepted[:max(1, min(int(limit), 50))],
        "count": min(len(accepted), max(1, min(int(limit), 50))),
        "summary": {"source_opportunities": len(rows), "unverified_ev": unverified,
                    "matching_filter": len(accepted)},
        "filters": {"min_ev": min_ev, "requires_verified_ev": min_ev is not None},
        "odds": odds, "odds_applied": False,
        "ev_note": "EV filters require explicitly verified offer-specific payout evidence. Assumed odds never change the shared forecast.",
        "cache": {"hit": bool(selected["available"]), "source": "daily_snapshot"},
    }
    return scored_opportunities(payload, "opportunities")
