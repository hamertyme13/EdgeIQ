from models.entry import Entry


def recommendation(entry: Entry) -> dict:
    confidence = entry.average_confidence
    edge = entry.average_edge
    source_score = _average_source_score(entry)
    prop_count = entry.prop_count
    score = _entry_score(confidence, edge, source_score, prop_count)

    if score >= 78:

        return {
            "grade": "A",
            "action": "🟢 Submit Entry",
            "reason": _reason("Excellent blended score.", confidence, edge, source_score),
            "color": "green",
            "score": score,
            "components": _components(confidence, edge, source_score, prop_count),
        }

    elif score >= 66:

        return {
            "grade": "B",
            "action": "🟡 Worth Considering",
            "reason": _reason("Solid blended score.", confidence, edge, source_score),
            "color": "yellow",
            "score": score,
            "components": _components(confidence, edge, source_score, prop_count),
        }

    elif score >= 55:

        return {
            "grade": "C",
            "action": "⚪ Borderline",
            "reason": _reason("Borderline blended score.", confidence, edge, source_score),
            "color": "cyan",
            "score": score,
            "components": _components(confidence, edge, source_score, prop_count),
        }

    return {
        "grade": "F",
        "action": "🔴 Pass",
        "reason": _reason("Entry score is too low.", confidence, edge, source_score),
        "color": "red",
        "score": score,
        "components": _components(confidence, edge, source_score, prop_count),
    }


def _entry_score(confidence: float, edge: float, source_score: float, prop_count: int) -> float:
    edge_boost = max(-15.0, min(15.0, edge * 4.0))
    source_boost = max(-8.0, min(8.0, source_score * 0.5))
    leg_penalty = max(0, prop_count - 3) * 2.0
    return round(max(0.0, min(100.0, confidence + edge_boost + source_boost - leg_penalty)), 2)


def _average_source_score(entry: Entry) -> float:
    if not entry.props:
        return 0.0
    return sum(float(getattr(prop, "source_score", 0.0) or 0.0) for prop in entry.props) / len(entry.props)


def _components(confidence: float, edge: float, source_score: float, prop_count: int) -> dict:
    return {
        "average_confidence": round(confidence, 2),
        "average_edge": round(edge, 2),
        "average_source_score": round(source_score, 2),
        "prop_count": prop_count,
    }


def _reason(prefix: str, confidence: float, edge: float, source_score: float) -> str:
    return (
        f"{prefix} Confidence {confidence:.1f}%, edge {edge:+.2f}, "
        f"source support {source_score:+.1f}."
    )
