from __future__ import annotations

from analytics.prediction_evidence import deduplicate_outcomes


def evaluate_model_versions(rows: list[dict]) -> dict:
    eligible = deduplicate_outcomes([
        row for row in rows
        if not row.get("legacy_quarantined")
        and row.get("result") in {"Win", "Loss"}
        and row.get("probability") not in (None, "")
        and str(row.get("outcome_source") or "").lower() not in {"", "unknown", "unmatched", "projection_estimate"}
    ])
    grouped: dict[str, list[dict]] = {}
    for row in eligible:
        grouped.setdefault(str(row.get("model_version") or "unknown"), []).append(row)
    versions = [_version_metrics(version, version_rows) for version, version_rows in sorted(grouped.items())]
    return {
        "versions": versions,
        "segments": _segment_metrics(eligible),
        "v2_4_vs_v2_3": _compare_families(versions, "v2.4", "v2.3"),
        "history_filter_comparison": _history_filter_metrics(eligible),
        "message": "Metrics use independent, versioned, provider-settled prop outcomes only.",
    }


def _version_metrics(version: str, rows: list[dict]) -> dict:
    probabilities = [_probability(row) for row in rows]
    outcomes = [_outcome(row) for row in rows]
    brier = sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes, strict=False)) / len(rows)
    predicted = sum(probabilities) / len(rows)
    actual = sum(outcomes) / len(rows)
    brier_score = round(brier, 4)
    calibration_gap = round((actual - predicted) * 100.0, 1)
    return {
        "model_version": version,
        "settled_predictions": len(rows),
        "brier_score": brier_score,
        "predicted_hit_rate": round(predicted * 100.0, 1),
        "actual_hit_rate": round(actual * 100.0, 1),
        "calibration_gap": calibration_gap,
        "promotion_eligible": len(rows) >= 200 and brier_score <= 0.20 and abs(calibration_gap) <= 7.5,
        "calibration_buckets": _buckets(rows),
    }


def _segment_metrics(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (
            str(row.get("sport") or "Unknown").upper(),
            str(row.get("stat") or "Unknown"),
            str(row.get("platform") or "Unknown"),
        )
        grouped.setdefault(key, []).append(row)
    segments = []
    for (sport, stat, provider), selected in grouped.items():
        probabilities = [_probability(row) for row in selected]
        outcomes = [_outcome(row) for row in selected]
        brier = sum(
            (probability - outcome) ** 2
            for probability, outcome in zip(probabilities, outcomes, strict=False)
        ) / len(selected)
        predicted = sum(probabilities) / len(selected)
        actual = sum(outcomes) / len(selected)
        samples = len(selected)
        segments.append({
            "sport": sport,
            "stat": stat,
            "provider": provider,
            "samples": samples,
            "brier_score": round(brier, 4),
            "calibration_gap": round((actual - predicted) * 100.0, 1),
            "maturity": "mature" if samples >= 500 else "evaluating" if samples >= 100 else "paper_only",
            "paid_eligible": samples >= 100 and brier <= 0.22 and abs(actual - predicted) <= 0.10,
        })
    return sorted(segments, key=lambda row: (-row["samples"], row["sport"], row["stat"], row["provider"]))


def _buckets(rows: list[dict]) -> list[dict]:
    buckets = []
    for low in range(40, 100, 10):
        selected = [row for row in rows if low <= float(row.get("probability") or 0.0) < low + 10]
        if not selected:
            continue
        predicted = sum(_probability(row) for row in selected) / len(selected)
        actual = sum(_outcome(row) for row in selected) / len(selected)
        buckets.append({
            "label": f"{low}-{low + 10}%", "samples": len(selected),
            "predicted": round(predicted * 100.0, 1), "actual": round(actual * 100.0, 1),
            "gap": round((actual - predicted) * 100.0, 1),
        })
    return buckets


def _compare_families(versions: list[dict], current: str, prior: str) -> dict:
    current_rows = [row for row in versions if current in row["model_version"]]
    prior_rows = [row for row in versions if prior in row["model_version"]]
    if not current_rows or not prior_rows:
        return {"ready": False, "message": "Both v2.4 and v2.3 need settled versioned outcomes before comparison."}
    current_best = max(current_rows, key=lambda row: row["settled_predictions"])
    prior_best = max(prior_rows, key=lambda row: row["settled_predictions"])
    return {
        "ready": True, "current": current_best, "prior": prior_best,
        "brier_improvement": round(float(prior_best["brier_score"]) - float(current_best["brier_score"]), 4),
    }


def _history_filter_metrics(rows: list[dict]) -> dict:
    pairs = []
    for row in rows:
        comparison = ((row.get("feature_snapshot") or {}).get("features") or {}).get("history_filter_comparison") or {}
        current = (comparison.get("current_season") or {}).get("probability")
        trailing = (comparison.get("trailing_history") or {}).get("probability")
        if current is None or trailing is None:
            continue
        outcome = _outcome(row)
        pairs.append((float(current) / 100.0, float(trailing) / 100.0, outcome))
    if not pairs:
        return {"ready": False, "samples": 0, "message": "New v2.4 outcomes will populate this comparison."}
    current_brier = sum((current - outcome) ** 2 for current, _, outcome in pairs) / len(pairs)
    trailing_brier = sum((trailing - outcome) ** 2 for _, trailing, outcome in pairs) / len(pairs)
    return {
        "ready": True, "samples": len(pairs), "current_season_brier": round(current_brier, 4),
        "trailing_history_brier": round(trailing_brier, 4),
        "preferred": "current-season" if current_brier <= trailing_brier else "trailing-history",
    }


def _probability(row: dict) -> float:
    return max(0.0, min(1.0, float(row.get("probability") or 0.0) / 100.0))


def _outcome(row: dict) -> float:
    return 1.0 if row.get("result") == "Win" else 0.0
