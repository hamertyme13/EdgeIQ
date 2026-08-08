from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from analytics.prediction_evidence import deduplicate_outcomes
from utils.stat_normalization import stat_key

EXCLUDED_FINAL_SOURCES = {"", "unknown", "unmatched", "projection_estimate"}


def verified_prop(prop: dict) -> bool:
    return (
        prop.get("final_result") in {"Win", "Loss", "Push", "DNP"}
        and str(prop.get("final_source") or "").strip().lower()
        not in EXCLUDED_FINAL_SOURCES
    )


def verified_settled_entries(entries: list[dict]) -> list[dict]:
    rows = []
    for entry in entries:
        props = entry.get("props") or []
        if (
            entry.get("status") == "Settled"
            and entry.get("result") in {"Win", "Loss"}
            and props
            and all(verified_prop(prop) for prop in props)
        ):
            rows.append(entry)
    return rows


def outcome_comparison(
    entries: list[dict],
    limit: int = 10,
    clv_for_prop: Callable[[dict], dict] | None = None,
) -> dict:
    verified = verified_settled_entries(entries)
    wins = [entry for entry in verified if entry.get("result") == "Win"]
    losses = [entry for entry in verified if entry.get("result") == "Loss"]
    win_profile = _profile(wins, clv_for_prop)
    loss_profile = _profile(losses, clv_for_prop)
    segments = _segment_rows(verified)
    return {
        "summary": {
            "wins_reviewed": len(wins),
            "losses_reviewed": len(losses),
            "verified_entries": len(verified),
            "excluded_unverified": sum(
                1
                for entry in entries
                if entry.get("status") == "Settled"
                and entry.get("result") in {"Win", "Loss"}
                and entry not in verified
            ),
        },
        "profiles": {"wins": win_profile, "losses": loss_profile},
        "insights": _comparison_insights(win_profile, loss_profile, len(wins), len(losses)),
        "learning_segments": segments,
        "model_feedback": {
            "active": any(row["model_eligible"] for row in segments),
            "eligible_segments": sum(1 for row in segments if row["model_eligible"]),
            "minimum_verified_legs": 20,
            "maximum_adjustment_points": 5.0,
            "message": "Only verified final stats influence recommendation confidence.",
        },
        "entries": [
            _entry_explanation(entry, clv_for_prop)
            for entry in verified[: max(1, min(limit, 50))]
        ],
    }


def _profile(entries: list[dict], clv_for_prop: Callable[[dict], dict] | None) -> dict:
    props = [prop for entry in entries for prop in entry.get("props") or []]
    clv = [
        value
        for prop in props
        if (value := _clv(prop, clv_for_prop)) is not None
    ]
    return {
        "entries": len(entries),
        "verified_legs": len(props),
        "avg_confidence": _average(float(prop.get("confidence") or 0) for prop in props),
        "avg_edge": _average(float(prop.get("edge") or 0) for prop in props),
        "avg_legs": _average(len(entry.get("props") or []) for entry in entries),
        "provider_backed_pct": _percent(
            sum(1 for prop in props if not prop.get("auto_projected")), len(props)
        ),
        "positive_clv_pct": _percent(sum(1 for value in clv if value > 0), len(clv)),
    }


def _entry_explanation(entry: dict, clv_for_prop: Callable[[dict], dict] | None) -> dict:
    props = entry.get("props") or []
    result = entry.get("result") or ""
    clv = [_clv(prop, clv_for_prop) for prop in props]
    reasons = []
    if all(not prop.get("auto_projected") for prop in props):
        reasons.append("Every leg used provider-backed evidence")
    if any(value is not None and value > 0 for value in clv):
        reasons.append("Captured positive closing-line value")
    if any(value is not None and value < 0 for value in clv):
        reasons.append("Accepted a worse line than the closing market")
    if any(float(prop.get("confidence") or 0) < 55 for prop in props):
        reasons.append("Included a low-confidence leg")
    if any(prop.get("auto_projected") for prop in props):
        reasons.append("Relied on an auto-projected leg")
    games = [prop.get("game") for prop in props if prop.get("game")]
    if len(games) != len(set(games)):
        reasons.append("Combined correlated legs from the same game")
    if len(props) >= 4:
        reasons.append("Required four or more legs to hit")
    if not reasons:
        reasons.append("Normal outcome variance was the main observable factor")
    return {
        "id": entry.get("id"),
        "result": result,
        "platform": entry.get("platform", ""),
        "placed_at": entry.get("placed_at"),
        "leg_count": len(props),
        "reasons": reasons,
        "legs": [
            {
                "player": prop.get("player", ""),
                "stat": prop.get("stat", ""),
                "line": prop.get("line"),
                "direction": prop.get("direction", "Over"),
                "actual": prop.get("actual"),
                "result": prop.get("final_result", ""),
                "source": prop.get("final_source", ""),
            }
            for prop in props
        ],
    }


def _segment_rows(entries: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for entry in entries:
        for prop in entry.get("props") or []:
            row = {**prop, "result": prop.get("final_result")}
            values = {
                "Sport": str(prop.get("sport") or "Unknown").upper(),
                "Stat": stat_key(prop.get("stat") or "Unknown"),
                "Platform": str(prop.get("platform") or entry.get("platform") or "Unknown"),
                "Direction": str(prop.get("direction") or "Over"),
                "Confidence": _confidence_band(prop.get("confidence")),
            }
            for dimension, value in values.items():
                groups[(dimension, value)].append(row)
    segments = []
    for (dimension, value), raw_rows in groups.items():
        rows = deduplicate_outcomes(raw_rows)
        wins = sum(1 for row in rows if row.get("result") == "Win")
        losses = sum(1 for row in rows if row.get("result") == "Loss")
        decisions = wins + losses
        if decisions < 5:
            continue
        actual = wins / decisions * 100
        predicted = _average(float(row.get("confidence") or 0) for row in rows)
        segments.append({
            "dimension": dimension,
            "name": value,
            "verified_legs": decisions,
            "wins": wins,
            "losses": losses,
            "hit_rate": round(actual, 1),
            "avg_confidence": predicted,
            "calibration_gap": round(actual - predicted, 1),
            "model_eligible": decisions >= 20,
        })
    return sorted(
        segments,
        key=lambda row: (row["model_eligible"], row["verified_legs"]),
        reverse=True,
    )[:16]


def _comparison_insights(wins: dict, losses: dict, win_count: int, loss_count: int) -> list[str]:
    if not win_count or not loss_count:
        return ["More verified wins and losses are needed for a reliable comparison."]
    insights = []
    comparisons = (
        ("avg_legs", "Winning entries used {direction} legs ({win:.1f} vs {loss:.1f}).", "more", "fewer"),
        ("provider_backed_pct", "Winning entries used {direction} provider-backed legs ({win:.1f}% vs {loss:.1f}%).", "more", "fewer"),
        ("positive_clv_pct", "Winning entries captured {direction} positive CLV ({win:.1f}% vs {loss:.1f}%).", "more", "less"),
        ("avg_confidence", "Winning legs carried {direction} recorded confidence ({win:.1f}% vs {loss:.1f}%).", "higher", "lower"),
    )
    for key, template, greater, lesser in comparisons:
        win_value = float(wins.get(key) or 0)
        loss_value = float(losses.get(key) or 0)
        if abs(win_value - loss_value) < (0.25 if key == "avg_legs" else 2.0):
            continue
        direction = greater if win_value > loss_value else lesser
        insights.append(template.format(direction=direction, win=win_value, loss=loss_value))
    return insights[:4] or ["Verified wins and losses currently have similar observable profiles."]


def _confidence_band(value: object) -> str:
    confidence = max(0.0, min(100.0, float(value or 0)))
    floor = min(90, int(confidence // 10) * 10)
    return f"{floor}-{floor + 10}%"


def _clv(prop: dict, callback: Callable[[dict], dict] | None) -> float | None:
    if callback is None:
        return None
    try:
        value = callback(prop).get("clv")
        return None if value is None else float(value)
    except (AttributeError, TypeError, ValueError):
        return None


def _average(values) -> float:
    rows = list(values)
    return round(sum(rows) / len(rows), 1) if rows else 0.0


def _percent(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0
