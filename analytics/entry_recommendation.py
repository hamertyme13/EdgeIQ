from __future__ import annotations

import math

from models.entry import Entry

_STANDARD_MULTIPLIERS = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 37.5, 7: 70.0, 8: 100.0}


def recommendation(entry: Entry) -> dict:
    confidence = entry.average_confidence
    card_probability = _card_probability(entry)
    break_even = 100.0 / _STANDARD_MULTIPLIERS.get(entry.prop_count, max(1.0, float(entry.prop_count)))
    probability_margin = card_probability - break_even
    edge = entry.average_edge
    source_score = _average_source_score(entry)
    prop_count = entry.prop_count
    score = _entry_score(card_probability, probability_margin, edge, source_score, prop_count)

    if score >= 78:

        return {
            "grade": "A",
            "action": "🟢 Submit Entry",
            "reason": _reason("Excellent blended score.", confidence, edge, source_score),
            "color": "green",
            "score": score,
            "components": _components(confidence, edge, source_score, prop_count, card_probability, break_even),
        }

    elif score >= 66:

        return {
            "grade": "B",
            "action": "🟡 Worth Considering",
            "reason": _reason("Solid blended score.", confidence, edge, source_score),
            "color": "yellow",
            "score": score,
            "components": _components(confidence, edge, source_score, prop_count, card_probability, break_even),
        }

    elif score >= 55:

        return {
            "grade": "C",
            "action": "⚪ Borderline",
            "reason": _reason("Borderline blended score.", confidence, edge, source_score),
            "color": "cyan",
            "score": score,
            "components": _components(confidence, edge, source_score, prop_count, card_probability, break_even),
        }

    return {
        "grade": "F",
        "action": "🔴 Pass",
        "reason": _reason("Entry score is too low.", confidence, edge, source_score),
        "color": "red",
        "score": score,
        "components": _components(confidence, edge, source_score, prop_count, card_probability, break_even),
    }


def _entry_score(card_probability: float, probability_margin: float, edge: float, source_score: float, prop_count: int) -> float:
    edge_boost = max(-15.0, min(15.0, edge * 4.0))
    source_boost = max(-8.0, min(8.0, source_score * 0.5))
    margin_score = 50.0 + probability_margin * 3.0
    leg_penalty = max(0, prop_count - 3) * 1.5
    return round(max(0.0, min(100.0, margin_score + edge_boost + source_boost - leg_penalty)), 2)


def _card_probability(entry: Entry) -> float:
    probabilities = [max(0.01, min(0.99, float(prop.confidence) / 100.0)) for prop in entry.props]
    return math.prod(probabilities) * 100.0 if probabilities else 0.0


def _average_source_score(entry: Entry) -> float:
    if not entry.props:
        return 0.0
    return sum(float(getattr(prop, "source_score", 0.0) or 0.0) for prop in entry.props) / len(entry.props)


def _components(confidence: float, edge: float, source_score: float, prop_count: int, card_probability: float, break_even: float) -> dict:
    return {
        "average_confidence": round(confidence, 2),
        "average_edge": round(edge, 2),
        "average_source_score": round(source_score, 2),
        "prop_count": prop_count,
        "calibrated_card_probability": round(card_probability, 2),
        "break_even_probability": round(break_even, 2),
        "probability_margin": round(card_probability - break_even, 2),
    }


def _reason(prefix: str, confidence: float, edge: float, source_score: float) -> str:
    return (
        f"{prefix} Confidence {confidence:.1f}%, edge {edge:+.2f}, "
        f"source support {source_score:+.1f}."
    )
