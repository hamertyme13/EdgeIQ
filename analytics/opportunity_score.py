"""Presentation-only scoring. Never authorizes an entry or changes a forecast."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime

SCORE_VERSION = "edgeiq-score-v1"
WEIGHTS = {"model": 0.40, "data_quality": 0.25, "history": 0.15, "market": 0.20}


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value))
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def score_label(score: float) -> str:
    for threshold, label in ((90, "Elite"), (80, "Strong"), (70, "Watch"), (60, "Marginal")):
        if score >= threshold:
            return label
    return "Pass"


def score_source_freshness(prop: dict, *, now: datetime | None = None) -> dict:
    current = now or datetime.now(UTC)
    # Repository DateTime values are UTC without tzinfo, not local wall time.
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
    age = None
    try:
        timestamp = datetime.fromisoformat(str(prop.get("feature_as_of") or "").replace("Z", "+00:00"))
        if timestamp.tzinfo is not None:
            age = (current - timestamp.astimezone(UTC)).total_seconds() / 60
    except ValueError:
        pass
    source_status = (prop.get("recommendation_freshness") or {}).get("status")
    market_stale = ((prop.get("decision_receipt") or {}).get("market_consensus") or {}).get("stale")
    if age is None or age < 0 or source_status == "unknown":
        status = "unknown"
    elif age > 30 or source_status in {"expired", "stale"} or market_stale:
        status = "expired"
    else:
        status = "fresh"
    return {"status": status, "age_minutes": round(age, 1) if age is not None else None,
            "label": {"fresh": "Current evidence", "expired": "Expired - refresh required",
                      "unknown": "Freshness unavailable - refresh required"}[status]}


def opportunity_score(prop: dict, *, now: datetime | None = None) -> dict:
    """Consume percent-unit probabilities and existing policy decisions, fail closed."""
    receipt = prop.get("decision_receipt") or {}
    forecast = prop.get("forecast_snapshot") or {}
    probability = _number(receipt.get("probability"))
    if probability is None:
        probability = _number(prop.get("confidence"))
    quality = _number((prop.get("data_quality") or {}).get("score"))
    sample = _number((prop.get("hit_rate") or {}).get("sample_size"))
    if sample is None:
        sample = _number(forecast.get("effective_sample_size"))
    if sample is None:
        sample = _number(prop.get("history_sample"))
    market = _number(receipt.get("market_probability"))
    valid_probability = probability is not None and 0 <= probability <= 100
    valid_market = market is not None and 0 <= market <= 100
    components: dict[str, float] = {
        "model": probability if probability is not None and valid_probability else 0.0,
        "data_quality": _bounded(quality or 0.0),
        "history": _bounded(max(0.0, sample or 0.0) * 5),
        "market": _bounded(50 + ((probability or 0) - (market or 0)) * 5)
        if valid_market and valid_probability else 0.0,
    }
    missing = []
    if not valid_probability:
        missing.append("Model probability is unavailable or invalid.")
    if quality is None or not 0 <= quality <= 100:
        missing.append("Data quality has not been verified.")
    if sample is None:
        missing.append("Comparable player history is unavailable.")
    if not valid_market:
        missing.append("Exact-line market comparison is unavailable.")

    restrictions = []
    if not valid_probability or quality is None or not 60 <= quality <= 100:
        restrictions.append("Evidence quality is not sufficient for a high score.")
    if sample is None or sample < 20:
        restrictions.append("Small sample: fewer than 20 comparable player games.")
    if prop.get("forecast_paid_eligible") is not True:
        restrictions.append("This model segment has not cleared paid-use evidence requirements.")
    policy = prop.get("recommendation_eligibility") or {}
    if policy.get("paid_ready") is not True:
        restrictions.append("The recommendation policy has not cleared this market for paid use.")

    if score_source_freshness(prop, now=now)["status"] != "fresh":
        restrictions.append("Source freshness is unverified or older than 30 minutes.")

    penalties = {
        "push_risk": -round(_bounded(_number((prop.get("push_risk") or {}).get("score")) or 0) * .10, 2),
        "correlation": -round(_bounded(_number(prop.get("correlation_risk_score")) or 0) * .10, 2),
    }
    raw = sum(float(components[key]) * weight for key, weight in WEIGHTS.items())
    before_cap = round(_bounded(raw + sum(penalties.values())), 1)
    cap = 59.0 if restrictions else 79.0 if not valid_market else 100.0
    score = min(before_cap, cap)
    penalties["evidence_cap"] = round(score - before_cap, 1)
    return {
        "score": score, "label": score_label(score), "version": SCORE_VERSION,
        "components": {key: round(float(value), 1) for key, value in components.items()},
        "weights": WEIGHTS.copy(), "penalties": penalties,
        "missing_evidence": missing, "restrictions": restrictions,
        "sample_size": sample, "small_sample": sample is None or sample < 20,
        "summary": restrictions[0] if restrictions else (
            "Compare the model, history, and exact-line market evidence before reviewing the complete entry."
        ),
        "meaning": "Research score, not win probability or permission to place a paid entry.",
    }


def score_input_digest(prop: dict) -> str:
    """Bind a stored score to its offer identity and every scoring input."""
    fields = (
        "player", "player_identity_id", "sport", "stat", "platform", "game", "game_time",
        "direction", "line", "provider_offer_id", "provider_event_id", "model_version",
        "confidence", "data_quality", "hit_rate", "forecast_snapshot", "history_sample",
        "decision_receipt", "forecast_paid_eligible", "recommendation_eligibility",
        "feature_as_of", "recommendation_freshness", "push_risk", "correlation_risk_score",
    )
    encoded = json.dumps({key: prop.get(key) for key in fields}, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def locked_opportunity_score(prop: dict, snapshot_id: str, captured_at: datetime) -> dict:
    captured_at = captured_at.replace(tzinfo=UTC) if captured_at.tzinfo is None else captured_at.astimezone(UTC)
    return {
        **opportunity_score(prop, now=captured_at),
        "snapshot_id": snapshot_id,
        "scored_at": captured_at.isoformat(),
        "input_digest": score_input_digest(prop),
    }
