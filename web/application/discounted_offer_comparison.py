"""Research-only discounted PrizePicks comparisons for standard recommendations."""

from __future__ import annotations

import math
from dataclasses import fields

from analytics.hierarchical_calibration import calibrate_probability
from analytics.probabilistic_forecast import PropForecast, forecast_probability_at_line
from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from utils.stat_normalization import canonical_stat_label


def _market_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        canonical_person_key(row.get("player")),
        canonical_stat_label(row.get("stat")),
        str(row.get("sport") or row.get("league") or "").upper(),
        canonical_matchup_key(row.get("game")),
        str(row.get("game_time") or ""),
    )


def _line(row: dict) -> float | None:
    try:
        value = float(row.get("line"))
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _forecast(row: dict) -> PropForecast | None:
    snapshot = row.get("forecast_snapshot") or {}
    if not isinstance(snapshot, dict) or snapshot.get("source") != "verified_history_distribution":
        return None
    try:
        return PropForecast(**{field.name: snapshot[field.name] for field in fields(PropForecast)})
    except (KeyError, TypeError, ValueError):
        return None


def attach_discounted_options(
    recommendations: list[dict], offers: list[dict], calibration_rows: list[dict],
) -> None:
    """Add one closest favorable line; never alter a standard recommendation's score."""
    by_market: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for offer in offers:
        if str(offer.get("platform") or "").lower() != "prizepicks":
            continue
        if str(offer.get("line_offer_type") or offer.get("odds_type") or "").lower() != "goblin":
            continue
        key = _market_key(offer)
        if all(key) and _line(offer) is not None:
            by_market.setdefault(key, []).append(offer)

    for prop in recommendations:
        if str(prop.get("platform") or "").lower() != "prizepicks":
            continue
        if str(prop.get("line_offer_type") or "standard").lower() != "standard":
            continue
        standard_line = _line(prop)
        if standard_line is None:
            continue
        direction = str(prop.get("direction") or "").title()
        if direction not in {"Over", "Under"}:
            continue
        candidates = [offer for offer in by_market.get(_market_key(prop), [])
                      if direction in (offer.get("allowed_directions") or ["Over", "Under"])
                      and ((direction == "Over" and _line(offer) < standard_line)
                           or (direction == "Under" and _line(offer) > standard_line))]
        if not candidates:
            continue
        alternate = min(candidates, key=lambda offer: abs(_line(offer) - standard_line))
        discounted_line = _line(alternate)
        probability = None
        forecast = _forecast(prop)
        if forecast:
            raw_probability = forecast_probability_at_line(
                forecast, discounted_line, direction, str(prop.get("stat") or ""),
            )
            if raw_probability is not None:
                calibrated = calibrate_probability(
                    raw_probability / 100.0,
                    sport=str(prop.get("sport") or prop.get("league") or ""),
                    stat=str(prop.get("stat") or ""),
                    provider="PrizePicks", direction=direction,
                    projection_source=str(prop.get("projection_source") or forecast.source),
                    rows=calibration_rows,
                )
                probability = calibrated["probability"]
        prop["discounted_option"] = {
            "line": discounted_line,
            "direction": direction,
            "probability": probability,
            "offer_type": "goblin",
            "provider_player_id": alternate.get("provider_player_id") or alternate.get("player_id") or "",
            "provider_event_id": alternate.get("provider_event_id") or alternate.get("event_id") or alternate.get("game_id") or "",
            "provider_offer_id": alternate.get("provider_offer_id") or alternate.get("projection_id") or alternate.get("offer_id") or "",
            "allowed_directions": alternate.get("allowed_directions") or ["Over", "Under"],
            "observed_at": alternate.get("provider_offer_verified_at") or alternate.get("provider_offer_observed_at") or "",
        }
