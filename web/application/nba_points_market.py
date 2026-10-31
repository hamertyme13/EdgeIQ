"""On-demand, research-only exact-line NBA points market comparison."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import isfinite

_log = logging.getLogger(__name__)


def _utc(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def build_nba_points_market(
    player: str,
    line: float,
    platform: str,
    *,
    research: Callable[[str, str, str, str, float], dict],
    market_lookup: Callable[..., dict],
    capture_quote: Callable[[dict, dict, float | None, str], dict] | None = None,
    quote_history: Callable[[str, str, str, str, float], list[dict]] | None = None,
    now: datetime | None = None,
) -> dict:
    result = {
        "status": "unavailable",
        "reason": "No exact, current provider offer is available for this player and line.",
        "line": line,
        "market_over_probability": None,
        "market_under_probability": None,
        "model_over_probability": None,
        "model_market_gap": None,
        "ev": None,
        "payout_verified": False,
        "capture_status": "not_captured",
        "note": "External sportsbook prices do not establish a PrizePicks or Underdog payout. No validated edge or EV is claimed.",
    }
    if not isfinite(line) or line <= 0:
        return {**result, "reason": "Enter a valid Points line before checking the market."}

    payload = research(player, "Points", "NBA", platform, line)
    offers = []
    for offer in payload.get("active_props") or []:
        try:
            offer_line = float(offer["line"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isfinite(offer_line) or abs(offer_line - line) >= 0.001:
            continue
        if platform != "Both" and str(offer.get("platform") or "").lower() != platform.lower():
            continue
        offers.append(offer)
    identities = {(str(offer.get("game") or ""), str(offer.get("game_time") or "")) for offer in offers}
    if len(identities) != 1:
        return {**result, "reason": (
            "Several games match this player and line; select a specific current game."
            if identities else result["reason"]
        )}
    offer = next((row for row in offers if row.get("line_offer_type") == "standard"), offers[0])
    game_time = _utc(offer.get("game_time"))
    current = now or datetime.now(UTC)
    if game_time is None or game_time <= current:
        return {**result, "reason": "The exact offer has no verified future game start."}

    market = market_lookup(
        player, "Points", "NBA", str(offer.get("game") or ""), line,
        "Over", str(offer.get("team") or ""), str(offer.get("game_time") or ""),
    )
    if not market.get("available"):
        return {**result, "reason": str(market.get("reason") or "Exact-line paired odds are unavailable.")}
    try:
        market_line = float(str(market.get("line")))
        book_count = int(str(market.get("book_count")))
        timestamped_books = int(str(market.get("timestamped_book_count")))
    except (TypeError, ValueError):
        return {**result, "reason": "The sportsbook quote is incomplete or malformed."}
    if (market.get("source") != "The Odds API" or market.get("source_type") != "multi_book_no_vig"
            or book_count < 1 or not isfinite(market_line) or abs(market_line - line) >= 0.001):
        return {**result, "reason": "The returned odds do not match this exact Points line."}
    if timestamped_books != book_count:
        return {**result, "reason": "Some contributing sportsbook prices lack reliable timestamps."}
    event = market.get("event") or {}
    event_time = _utc(event.get("commence_time"))
    if not event.get("event_id") or event_time is None or abs(event_time - game_time) > timedelta(minutes=30):
        return {**result, "reason": "The sportsbook event cannot be matched to this provider game's start time."}
    updated = _utc(market.get("oldest_update"))
    if market.get("stale") or updated is None or current - updated > timedelta(minutes=30) or updated > current + timedelta(minutes=2):
        return {**result, "reason": "The exact-line sportsbook quote is stale or lacks a reliable timestamp."}
    over = market.get("over_probability")
    under = market.get("under_probability")
    try:
        over = float(str(over))
        under = float(str(under))
    except (TypeError, ValueError):
        return {**result, "reason": "Paired Over and Under market probabilities are incomplete."}
    if not all(isfinite(value) and 0 <= value <= 100 for value in (over, under)) or abs(over + under - 100) > 1:
        return {**result, "reason": "The paired market probabilities are inconsistent."}

    recommendation = payload.get("recommendation") or {}
    recommendation_line = recommendation.get("line")
    try:
        recommendation_line = float(str(recommendation_line))
    except (TypeError, ValueError):
        recommendation_line = None
    same_forecast_game = (
        recommendation_line is not None
        and isfinite(recommendation_line)
        and abs(recommendation_line - line) < 0.001
        and str(recommendation.get("game") or "") == str(offer.get("game") or "")
        and str(recommendation.get("game_time") or "") == str(offer.get("game_time") or "")
    )
    model = ((payload.get("nba_points_intelligence") or {}).get("projection") or {}).get("over_probability")
    model_source = ((payload.get("nba_points_intelligence") or {}).get("projection") or {}).get("source")
    try:
        model = float(model) if same_forecast_game and model is not None and model_source == "verified_history_distribution" else None
    except (TypeError, ValueError):
        model = None
    if model is not None and (not isfinite(model) or not 0 <= model <= 100):
        model = None
    capture_status = "not_configured"
    quote_snapshot_id = None
    saved_history: list[dict] = []
    history_status = "not_available"
    if capture_quote is not None:
        try:
            model_version = str(((payload.get("nba_points_intelligence") or {}).get("projection") or {}).get("model_version") or "")
            saved = capture_quote(offer, market, model, model_version)
            quote_snapshot_id = saved["id"]
            capture_status = "captured"
        except Exception:
            _log.exception("Validated NBA Points market quote could not be stored")
            capture_status = "failed"
    if capture_status == "captured" and quote_history is not None:
        try:
            saved_history = quote_history(
                player, str(offer.get("platform") or ""), str(offer.get("game") or ""),
                str(offer.get("game_time") or ""), line,
            )
            history_status = "available"
        except Exception:
            _log.exception("NBA Points market quote history could not be read")
            history_status = "failed"
    movement = (
        round(saved_history[-1]["market_over_probability"] - saved_history[0]["market_over_probability"], 2)
        if len(saved_history) >= 2 else None
    )
    return {
        **result,
        "status": "research_comparison",
        "reason": "Exact-line no-vig sportsbook context; the model gap is not a validated betting edge.",
        "market_over_probability": round(over, 2),
        "market_under_probability": round(under, 2),
        "model_over_probability": round(model, 2) if model is not None else None,
        "model_market_gap": round(model - over, 2) if model is not None else None,
        "book_count": book_count,
        "oldest_update": updated.isoformat(),
        "source": str(market.get("source") or "The Odds API"),
        "event_id": str(event["event_id"]),
        "event_time": event_time.isoformat(),
        "capture_status": capture_status,
        "quote_snapshot_id": quote_snapshot_id,
        "quote_history_status": history_status,
        "quote_history": saved_history,
        "market_over_movement_points": movement,
        "best_over_odds": market.get("best_over_odds"),
        "best_under_odds": market.get("best_under_odds"),
    }
