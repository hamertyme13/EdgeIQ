"""Deterministic support and failure cases for an individual prop recommendation."""
from __future__ import annotations

import math


def _number(value: object) -> float | None:
    try:
        number = float(str(value)) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number is not None and math.isfinite(number) else None


def counterargument(prop: dict) -> dict:
    """Score evidence fragility, not the probability that the prop loses.

    Weights and label boundaries are documented in docs/RECOMMENDATION_FRAGILITY.md.
    Missing evidence adds uncertainty; it never creates a favorable factor.
    """
    forecast = prop.get("forecast_snapshot") or {}
    features = forecast.get("features") or {}
    quality = prop.get("data_quality") or {}
    receipt = prop.get("decision_receipt") or {}
    exposure = receipt.get("portfolio_exposure") or {}
    eligibility = prop.get("recommendation_eligibility") or {}
    freshness = prop.get("recommendation_freshness") or {}
    sample = _number(forecast.get("effective_sample_size"))
    if sample is None:
        sample = _number(features.get("effective_sample_size"))
    projection = _number(prop.get("projection"))
    line = _number(prop.get("line"))
    sigma = _number(forecast.get("standard_deviation"))
    quality_score = _number(quality.get("score"))
    market_probability = _number(receipt.get("market_probability"))
    model_probability = _number(receipt.get("probability"))
    supporting: list[str] = []
    risks: list[str] = []
    invalidating: list[str] = []
    uncertainty = 0
    fragility = 0

    if sample is None:
        uncertainty += 20
        risks.append("Verified historical sample size is unavailable.")
    elif sample < 15:
        uncertainty += 20
        risks.append(f"Only {sample:g} effective historical games support this forecast.")
    elif sample < 30:
        uncertainty += 10
        risks.append(f"Historical sample is still limited ({sample:g} effective games).")
    else:
        supporting.append(f"Forecast uses {sample:g} effective historical games.")

    if sigma is None or projection is None:
        uncertainty += 15
        risks.append("Forecast spread is unavailable, so the line margin cannot be stress-checked.")
    elif sigma > 0 and abs(projection) > 0:
        relative_spread = sigma / abs(projection)
        if relative_spread >= 0.35:
            uncertainty += 15
            risks.append("Historical outcomes vary widely around the projection.")
        elif relative_spread >= 0.22:
            uncertainty += 8
            risks.append("Outcome variance is material relative to the projection.")
        if line is not None:
            margin = abs(projection - line) / sigma
            if margin < 0.25:
                fragility += 15
                risks.append("Projection is very close to the offered line.")
                invalidating.append("A small line or projection move can erase the modeled edge.")
            elif margin < 0.5:
                fragility += 8
                risks.append("A modest line move could weaken this recommendation.")
            else:
                supporting.append("Projection has room from the current line relative to historical spread.")

    if quality_score is None:
        uncertainty += 10
        risks.append("Data-quality score is unavailable.")
    elif quality_score < 50:
        uncertainty += 15
        risks.append("Underlying data quality is low.")
    elif quality_score < 70:
        uncertainty += 8
        risks.append("Underlying data quality is moderate.")
    else:
        supporting.append("Underlying data quality clears the stronger-evidence threshold.")

    freshness_status = str(freshness.get("status") or "unknown").lower()
    if freshness_status == "expired":
        fragility += 25
        risks.append("The provider offer is expired.")
        invalidating.append("Refresh the exact provider offer before using this line.")
    elif freshness_status != "fresh":
        fragility += 12
        risks.append("Current provider-offer freshness is unconfirmed.")
        invalidating.append("Confirm the exact offer is still available.")
    else:
        supporting.append("The provider offer is within its freshness window.")

    if features.get("role_evidence_required") and not features.get("role_evidence_verified"):
        fragility += 20
        risks.append("Required minutes or role evidence is not verified.")
        invalidating.append("Recheck after confirmed minutes, role, or lineup information arrives.")
    if prop.get("is_premium_line") or prop.get("line_offer_type") == "demon":
        fragility += 10
        risks.append("This adjusted offer may have a different payout or allowed direction.")
        invalidating.append("Confirm the provider's exact selection and card payout.")
    if exposure.get("same_market_entries"):
        fragility += 15
        risks.append("The same market already appears on a pending entry.")
        invalidating.append("Review shared-leg exposure before adding another card.")
    if market_probability is not None and model_probability is not None and model_probability >= 60 and market_probability < 50:
        fragility += 12
        risks.append("The exact-line market disagrees with the model's favored side.")
    if eligibility.get("paid_blocks"):
        fragility += 15
        risks.append("This leg has not cleared the paid-recommendation evidence policy.")
        invalidating.append("Keep it paper-first until the listed release blocks are resolved.")

    uncertainty = min(100, uncertainty)
    fragility = min(100, fragility + uncertainty)
    label = "Low" if fragility < 25 else "Moderate" if fragility < 50 else "High"
    return {
        "supporting_factors": supporting,
        "risk_factors": risks,
        "uncertainty_score": uncertainty,
        "fragility_score": fragility,
        "fragility_label": label,
        "invalidating_conditions": invalidating,
        "scoring_version": "edgeiq-fragility-v1",
    }
