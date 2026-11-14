"""Evidence gates for a daily 60%+ complete-card paper sample."""

from __future__ import annotations

from math import isfinite

from web.application.entry_creation_service import prepare_entry_analysis

MINIMUM_CARD_PROBABILITY = 60.0


def standard_line_offer(prop: dict) -> bool:
    offer_type = str(prop.get("line_offer_type") or prop.get("odds_type") or "standard").lower()
    if (offer_type != "standard" or prop.get("is_discounted_line")
            or prop.get("is_premium_line") or prop.get("adjusted_line")):
        return False
    standard = prop.get("standard_line")
    try:
        return standard in (None, "") or abs(float(prop["line"]) - float(standard)) <= 0.01
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def evaluated_standard_card_probability(suggestion) -> float | None:
    entry = getattr(suggestion, "entry", None)
    props = getattr(entry, "props", ())
    if len(props) != 2:
        return None
    for prop in props:
        snapshot = getattr(prop, "forecast_snapshot", None) or {}
        if snapshot.get("source") != "verified_history_distribution":
            return None
        if (getattr(prop, "is_discounted_line", False)
                or getattr(prop, "is_premium_line", False)
                or getattr(prop, "adjusted_line", False)
                or str(getattr(prop, "line_offer_type", "standard") or "standard").lower() != "standard"):
            return None
        standard = getattr(prop, "standard_line", None)
        try:
            if standard not in (None, "") and abs(float(prop.line) - float(standard)) > 0.01:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
    try:
        payout, _analysis = prepare_entry_analysis(
            entry, payout_type="standard", multiplier=1.0, audit_snapshot="{}",
        )
        probability = float(payout["all_hit_probability"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return probability if isfinite(probability) and MINIMUM_CARD_PROBABILITY <= probability <= 100 else None
