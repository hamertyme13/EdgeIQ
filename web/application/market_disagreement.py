"""Compare saved model forecasts with validated exact-line no-vig market evidence."""

from __future__ import annotations

from collections import Counter
from math import isfinite
from statistics import median

from services.betting import implied_probability
from utils.entity_normalization import canonical_person_key

MAX_MARKET_AGE_SECONDS = 1800


def _number(value: object) -> float | None:
    try:
        result = float(str(value))
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _probability(value: object) -> float | None:
    number = _number(value)
    return number if number is not None and 0 <= number <= 100 else None


def _valid_market(prop: dict) -> tuple[dict | None, str]:
    market = (prop.get("decision_receipt") or {}).get("market_consensus") or {}
    if not market.get("available") or market.get("source") != "The Odds API" or market.get("source_type") != "multi_book_no_vig":
        return None, "no_paired_market"
    age = _number(market.get("age_seconds"))
    if market.get("stale") or age is None or age < 0 or age > MAX_MARKET_AGE_SECONDS:
        return None, "stale_market"
    player_key = canonical_person_key(prop.get("player"))
    if not player_key or canonical_person_key(market.get("player")) != player_key:
        return None, "identity_mismatch"
    if str(market.get("stat") or "").casefold() != str(prop.get("stat") or "").casefold():
        return None, "stat_mismatch"
    if str(market.get("direction") or "").casefold() != str(prop.get("direction") or "").casefold():
        return None, "direction_mismatch"
    prop_line, market_line = _number(prop.get("line")), _number(market.get("line"))
    if prop_line is None or market_line is None or abs(prop_line - market_line) > 0.001:
        return None, "line_mismatch"
    books = market.get("books") or []
    book_count = _number(market.get("book_count"))
    if not isinstance(books, list) or not books or book_count is None or book_count != len(books):
        return None, "missing_paired_odds"
    fair_over = []
    for book in books:
        try:
            over, under = int(book["over_odds"]), int(book["under_odds"])
        except (KeyError, TypeError, ValueError):
            return None, "invalid_odds"
        if abs(over) < 100 or abs(under) < 100:
            return None, "invalid_odds"
        over_implied, under_implied = implied_probability(over), implied_probability(under)
        fair_over.append(100 * over_implied / (over_implied + under_implied))
    calculated = median(fair_over)
    if str(market["direction"]).casefold() == "under":
        calculated = 100 - calculated
    recorded = _probability(market.get("market_probability"))
    if recorded is None or abs(recorded - calculated) > 0.5:
        return None, "probability_conflict"
    return market, ""


def market_disagreement_payload(briefing: dict) -> dict:
    props = list(briefing.get("top_opportunities") or [])[:9]
    if (briefing.get("cache") or {}).get("stale"):
        return {
            "rows": [], "examined": len(props), "excluded": {"stale_briefing": len(props)},
            "as_of": briefing.get("as_of"),
            "message": "The saved briefing has expired. Refresh it before comparing model and market probabilities.",
        }
    excluded: Counter[str] = Counter()
    rows = []
    for prop in props:
        market, reason = _valid_market(prop)
        if not market:
            excluded[reason] += 1
            continue
        calibration = prop.get("calibration_presentation") or {}
        raw = _probability(calibration.get("model_probability"))
        calibrated = _probability(calibration.get("calibrated_probability"))
        if raw is None and calibrated is None:
            excluded["model_probability_unavailable"] += 1
            continue
        probability = float(market["market_probability"])
        raw_difference = round(raw - probability, 1) if raw is not None else None
        effective_difference = round(calibrated - probability, 1) if calibrated is not None else None
        sample = max(0, int(_number(calibration.get("segment_sample_size")) or 0))
        uncertainty = _number(calibration.get("uncertainty_points"))
        rows.append({
            "player": prop.get("player"), "sport": prop.get("sport"), "stat": prop.get("stat"),
            "direction": prop.get("direction"), "line": prop.get("line"), "platform": prop.get("platform"),
            "model_probability": raw, "calibrated_probability": calibrated,
            "market_probability": probability, "raw_difference": raw_difference,
            "effective_difference": effective_difference,
            "calibration_samples": sample,
            "calibration_uncertainty_points": uncertainty,
            "within_calibration_uncertainty": (
                abs(effective_difference) <= uncertainty
                if effective_difference is not None and uncertainty is not None and uncertainty >= 0 else None
            ),
            "market_book_count": len(market["books"]),
            "market_quality": market.get("quality") or "limited",
            "market_last_update": market.get("last_update") or "",
            "market_timestamp_coverage": int(_number(market.get("timestamped_book_count")) or 0),
            "snapshot_id": prop.get("leg_recommendation_snapshot_id") or prop.get("recommendation_snapshot_id") or "",
            "context": "One-book or thin-calibration evidence" if len(market["books"]) < 2 or sample < 100 else "Multi-book comparison; model uncertainty still applies",
        })
    rows.sort(key=lambda row: abs(row["effective_difference"] if row["effective_difference"] is not None
                                  else row["raw_difference"] or 0), reverse=True)
    return {
        "rows": rows, "examined": len(props), "excluded": dict(excluded),
        "as_of": briefing.get("as_of"),
        "message": (
            f"{len(rows)} exact-line no-vig comparison{'s' if len(rows) != 1 else ''} from the cached top-{len(props)} briefing opportunities."
            if rows else "No current top opportunity has matching, validated sportsbook odds and a model probability."
        ),
        "note": "Percentage-point differences are not expected value or profit estimates. Confirm provider payout and offer availability separately.",
    }
