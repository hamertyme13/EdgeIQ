"""On-demand, research-only exact-line NBA points market comparison."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import isfinite


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
        "note": "External sportsbook prices do not establish a PrizePicks or Underdog payout. No validated edge or EV is claimed.",
    }
    if not isfinite(line) or line <= 0:
        return {**result, "reason": "Enter a valid Points line before checking the market."}

    payload = research(player, "Points", "NBA", platform, line)
    offers = [
        offer for offer in payload.get("active_props") or []
        if offer.get("line") is not None and abs(float(offer["line"]) - line) < 0.001
    ]
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
    if (market.get("source") != "The Odds API" or market.get("source_type") != "multi_book_no_vig"
            or int(market.get("book_count") or 0) < 1 or abs(float(market.get("line") or 0) - line) >= 0.001):
        return {**result, "reason": "The returned odds do not match this exact Points line."}
    updated = _utc(market.get("oldest_update"))
    if market.get("stale") or updated is None or current - updated > timedelta(minutes=30) or updated > current + timedelta(minutes=2):
        return {**result, "reason": "The exact-line sportsbook quote is stale or lacks a reliable timestamp."}
    over = market.get("over_probability")
    under = market.get("under_probability")
    try:
        over = float(over)
        under = float(under)
    except (TypeError, ValueError):
        return {**result, "reason": "Paired Over and Under market probabilities are incomplete."}
    if not all(isfinite(value) and 0 <= value <= 100 for value in (over, under)) or abs(over + under - 100) > 1:
        return {**result, "reason": "The paired market probabilities are inconsistent."}

    recommendation = payload.get("recommendation") or {}
    same_forecast_game = (
        recommendation.get("line") is not None
        and abs(float(recommendation["line"]) - line) < 0.001
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
    return {
        **result,
        "status": "research_comparison",
        "reason": "Exact-line no-vig sportsbook context; the model gap is not a validated betting edge.",
        "market_over_probability": round(over, 2),
        "market_under_probability": round(under, 2),
        "model_over_probability": round(model, 2) if model is not None else None,
        "model_market_gap": round(model - over, 2) if model is not None else None,
        "book_count": int(market.get("book_count") or 0),
        "oldest_update": updated.isoformat(),
        "source": str(market.get("source") or "The Odds API"),
        "best_over_odds": market.get("best_over_odds"),
        "best_under_odds": market.get("best_under_odds"),
    }
