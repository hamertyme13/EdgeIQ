"""Keep provider verification time separate from model feature timestamps."""
from datetime import UTC, datetime
from math import isfinite

from utils.entity_normalization import canonical_matchup_key


def select_offer_line(candidates: list[dict], requested_line: float,
                      requested_offer_id: str = "") -> tuple[dict | None, dict | None]:
    """Select without mutating provider evidence or coercing missing lines to zero."""
    valid = []
    for row in candidates:
        value = row.get("line")
        if value is None or isinstance(value, bool):
            continue
        try:
            line = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if isfinite(line):
            valid.append((row, line))
    if not isfinite(requested_line):
        return None, None
    exact_rows = [row for row, line in valid if abs(line - requested_line) < 0.001]
    exact = next((row for row in exact_rows if requested_offer_id and str(
        row.get("provider_offer_id") or row.get("projection_id") or row.get("offer_id") or ""
    ) == requested_offer_id), next(iter(exact_rows), None))
    closest = min(valid, key=lambda item: abs(item[1] - requested_line), default=None)
    return exact, closest[0] if closest else None


def same_offer_game(requested: dict, candidate: dict) -> bool:
    """Reject conflicting event IDs or starts, including repeat matchups."""
    requested_id = str(requested.get("provider_event_id") or "")
    candidate_id = str(candidate.get("provider_event_id") or candidate.get("event_id") or candidate.get("game_id") or "")
    if requested_id and candidate_id and requested_id != candidate_id:
        return False
    starts = []
    for row in (requested, candidate):
        try:
            value = datetime.fromisoformat(str(row.get("game_time") or "").replace("Z", "+00:00"))
            starts.append(value.astimezone(UTC) if value.tzinfo else None)
        except ValueError:
            starts.append(None)
    if all(starts) and starts[0] != starts[1]:
        return False
    if requested_id and requested_id == candidate_id:
        return True
    return bool(all(starts) and starts[0] == starts[1]
                and requested.get("game") and candidate.get("game")
                and canonical_matchup_key(requested["game"]) == canonical_matchup_key(candidate["game"]))


def offer_freshness(row: dict, *, now: datetime | None = None) -> str:
    if row.get("stale"):
        return "expired"
    value = row.get("provider_offer_verified_at")
    if not value:
        return "unknown"
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if timestamp.tzinfo is None:
        return "unknown"
    age = ((now or datetime.now(UTC)) - timestamp).total_seconds()
    if age < 0:
        return "unknown"
    return "fresh" if age <= 300 else "expired"


def handoff_blocking_reason(status: str, line: float, identity: bool, freshness: str) -> str:
    if status == "changed":
        return f"The saved provider line is now {line:g}. Review the new line and reanalyze."
    if status != "current":
        return "No exact offer matched this game, stat, and direction. Confirm the matchup and offer in the sportsbook."
    if not identity:
        return "The provider offer ID is missing or changed. Reload the exact offer before handoff."
    if freshness == "expired":
        return "The provider evidence is stale. Refresh offers before handoff."
    if freshness != "fresh":
        return "Provider verification time is unavailable. Reanalysis alone cannot verify this offer."
    return ""
