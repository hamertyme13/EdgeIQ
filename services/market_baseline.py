"""Freeze only exact, timely, multi-book no-vig player odds as model baselines."""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from services.offer_snapshot import parsed_utc

MAX_BOOK_AGE = timedelta(minutes=30)
MAX_START_DIFFERENCE = timedelta(minutes=30)


def capture_market_baseline(row: dict, captured_at: datetime) -> tuple[dict | None, str]:
    receipt = row.get("decision_receipt") or {}
    market = receipt.get("market_consensus") if isinstance(receipt, dict) else None
    if not isinstance(market, dict) or not market.get("available"):
        return None, "exact_market_unavailable"
    if market.get("source_type") != "multi_book_no_vig" or market.get("stale"):
        return None, "source_unverified_or_stale"
    try:
        books = int(market.get("book_count") or 0)
    except (TypeError, ValueError, OverflowError):
        return None, "invalid_book_count"
    if books < 2:
        return None, "fewer_than_two_books"
    if market.get("timestamped_book_count") != books:
        return None, "book_timestamps_incomplete"
    try:
        probability = float(market["market_probability"])
        market_line = float(market["line"])
        offer_line = float(row["line"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, "invalid_market_terms"
    if not math.isfinite(probability) or not 0 < probability < 100 or not math.isclose(market_line, offer_line, abs_tol=1e-6):
        return None, "invalid_market_terms"
    direction = str(row.get("direction") or "Over")
    if market.get("direction") != direction:
        return None, "direction_mismatch"
    event = market.get("event") or {}
    offer_start = parsed_utc(row.get("game_time") or row.get("game_start"))
    market_start = parsed_utc(event.get("commence_time")) if isinstance(event, dict) else None
    if not isinstance(event, dict) or not event.get("event_id") or not offer_start or not market_start:
        return None, "game_identity_unavailable"
    if abs(offer_start - market_start) > MAX_START_DIFFERENCE:
        return None, "game_time_mismatch"
    if captured_at.tzinfo is None:
        return None, "market_timing_unverified"
    captured = captured_at.astimezone(UTC)
    observed = parsed_utc(market.get("oldest_update"))
    latest = parsed_utc(market.get("last_update"))
    if (not observed or not latest or observed > latest or latest > captured
            or captured - observed > MAX_BOOK_AGE or captured >= offer_start):
        return None, "market_timing_unverified"
    return {
        "probability": round(probability, 2),
        "observed_at": observed.isoformat(),
        "book_count": books,
        "source": "The Odds API exact-line no-vig",
        "event_id": str(event["event_id"]),
        "line": offer_line,
        "direction": direction,
    }, ""
