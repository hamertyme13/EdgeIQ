"""Stable market identity and independently dated provider evidence."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

from utils.entity_normalization import canonical_person_key
from utils.stat_normalization import canonical_stat_label

OFFER_EVIDENCE_TTL = timedelta(minutes=5)


def parsed_utc(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def canonical_offer(row: dict) -> dict | None:
    try:
        line_value = row.get("line")
        if line_value is None:
            return None
        line = float(str(line_value))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(line):
        return None
    allowed = row.get("allowed_directions", ["Over", "Under"])
    if not isinstance(allowed, list):
        allowed = []
    directions = sorted({str(item).title() for item in allowed if str(item).title() in {"Over", "Under"}})
    game_start = parsed_utc(row.get("game_time") or row.get("game_start") or row.get("scheduled_start"))
    return {
        "provider": str(row.get("platform") or row.get("provider") or "").strip(),
        "provider_offer_id": str(row.get("provider_offer_id") or row.get("projection_id") or row.get("offer_id") or ""),
        "provider_player_id": str(row.get("provider_player_id") or row.get("player_id") or ""),
        "provider_event_id": str(row.get("provider_event_id") or row.get("event_id") or row.get("game_id") or ""),
        "player_key": canonical_person_key(row.get("player") or row.get("player_name")),
        "sport": str(row.get("sport") or row.get("league") or "").upper(),
        "game": str(row.get("game") or ""),
        "game_start": game_start.isoformat() if game_start else "",
        "stat": canonical_stat_label(row.get("stat")),
        "allowed_directions": directions,
        "line": line,
        "offer_type": str(row.get("line_offer_type") or row.get("offer_type") or "standard").lower(),
        "standard_line": _finite_or_none(row.get("standard_line")),
        "baseline_line": _finite_or_none(row.get("baseline_line")),
        "discounted": bool(row.get("is_discounted_line") or row.get("adjusted_line")),
        "premium": bool(row.get("is_premium_line")),
    }


def offer_fingerprint(row: dict) -> str | None:
    offer = canonical_offer(row)
    if not offer or not all(offer[key] for key in ("provider", "player_key", "sport", "stat")):
        return None
    return hashlib.sha256(json.dumps(offer, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def observation_time(row: dict) -> datetime | None:
    return parsed_utc(row.get("provider_offer_verified_at") or row.get("provider_offer_observed_at"))


def evidence_status(row: dict, now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    start = parsed_utc(row.get("game_time") or row.get("game_start"))
    if start and start <= current:
        return "GAME_STARTED"
    if row.get("stale"):
        return "STALE"
    observed = observation_time(row)
    if not observed or observed > current:
        return "UNKNOWN"
    age = current - observed
    if age > OFFER_EVIDENCE_TTL:
        return "EXPIRED"
    return "AGING" if age > OFFER_EVIDENCE_TTL / 2 else "FRESH"


def _finite_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None
