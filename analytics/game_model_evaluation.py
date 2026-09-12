from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime

from analytics.game_model_registry import (
    GAME_CONTEXT_CHALLENGER_VERSION,
    GAME_HISTORICAL_BASELINE_VERSION,
    GAME_MARKET_CHAMPION_VERSION,
)


def promotion_evidence(rows: list[dict], candidate_version: str = GAME_CONTEXT_CHALLENGER_VERSION) -> dict:
    """Use a shared, pre-game three-model cohort, with one outcome per sport/game."""
    versions = {candidate_version, GAME_MARKET_CHAMPION_VERSION, GAME_HISTORICAL_BASELINE_VERSION}
    cohorts: dict[tuple[str, str, datetime], dict[str, dict]] = defaultdict(dict)
    now = datetime.now(UTC)
    for row in rows:
        generated = _timestamp(row.get("generated_at"))
        started = _timestamp(row.get("game_start"))
        settled = _timestamp(row.get("settled_at"))
        version = str(row.get("model_version") or "")
        if (version not in versions or generated is None or started is None or generated >= started
                or settled is None or not started < settled <= now
                or row.get("actual_home_win") not in (0.0, 1.0) or not row.get("outcome_source")
                or not row.get("settled_at") or not row.get("game_id")):
            continue
        if version == GAME_HISTORICAL_BASELINE_VERSION and not (row.get("evidence") or {}).get("historical_sample_size"):
            continue
        key = (str(row.get("sport") or ""), str(row["game_id"]), generated)
        cohorts[key][version] = row
    independent: dict[tuple[str, str], dict[str, dict]] = {}
    for key, cohort in sorted(cohorts.items(), key=lambda item: item[0][2]):
        if set(cohort) != versions or len({r["actual_home_win"] for r in cohort.values()}) != 1:
            continue
        independent.setdefault(key[:2], cohort)
    ordered = sorted(independent.values(), key=lambda cohort: _timestamp(cohort[candidate_version]["game_start"]) or datetime.min.replace(tzinfo=UTC))
    split = int(len(ordered) * 0.75)
    holdout = ordered[split:] if split else []
    metrics_by_version = {
        version: evaluate_game_predictions([cohort[version] for cohort in holdout]) for version in versions
    }
    candidate = metrics_by_version[candidate_version]
    brier = candidate["brier_score"]
    beats = {
        name: brier is not None and metrics_by_version[version]["brier_score"] is not None
        and brier < metrics_by_version[version]["brier_score"]
        for name, version in (("market", GAME_MARKET_CHAMPION_VERSION), ("historical", GAME_HISTORICAL_BASELINE_VERSION))
    }
    return {
        "method": "shared_chronological_pregame_holdout",
        "independent_games": len(ordered), "training_games": split, "holdout_games": len(holdout),
        "by_model": metrics_by_version,
        "metrics": candidate | {
            "chronological_holdout": bool(split and holdout),
            "beats_market_baseline": beats["market"], "beats_historical_baseline": beats["historical"],
        },
    }


def _timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def evaluate_game_predictions(rows: list[dict]) -> dict:
    settled = [row for row in rows if row.get("actual_home_win") is not None]
    if not settled:
        return {"settled_games": 0, "brier_score": None, "log_loss": None, "accuracy": None, "calibration_gap": None, "buckets": []}
    probabilities = [max(0.001, min(0.999, float(row["home_win_probability"]))) for row in settled]
    outcomes = [float(row["actual_home_win"]) for row in settled]
    brier = sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes, strict=False)) / len(settled)
    log_loss = -sum(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability) for probability, outcome in zip(probabilities, outcomes, strict=False)) / len(settled)
    accuracy = sum((probability >= 0.5) == bool(outcome) for probability, outcome in zip(probabilities, outcomes, strict=False)) / len(settled)
    buckets: list[dict] = []
    for start in range(0, 100, 10):
        bucket_rows = [(p, o) for p, o in zip(probabilities, outcomes, strict=False) if start <= p * 100 < start + 10]
        if bucket_rows:
            predicted = sum(p for p, _ in bucket_rows) / len(bucket_rows)
            actual = sum(o for _, o in bucket_rows) / len(bucket_rows)
            buckets.append({"bucket": f"{start}-{start + 10}%", "count": len(bucket_rows), "predicted": round(predicted * 100, 1), "actual": round(actual * 100, 1), "gap": round((actual - predicted) * 100, 1)})
    calibration_gap = sum(abs(row["gap"]) * row["count"] for row in buckets) / len(settled)
    return {
        "settled_games": len(settled),
        "brier_score": round(brier, 4),
        "log_loss": round(log_loss, 4),
        "accuracy": round(accuracy * 100, 1),
        "calibration_gap": round(calibration_gap, 2),
        "margin_mae": _mae(settled, "expected_margin", "actual_margin"),
        "total_mae": _mae(settled, "expected_total", "actual_total"),
        "home_score_mae": _mae(settled, "expected_home_points", "actual_home_points"),
        "away_score_mae": _mae(settled, "expected_away_points", "actual_away_points"),
        "buckets": buckets,
    }


def chronological_game_evaluation(rows: list[dict], *, holdout_fraction: float = 0.25) -> dict:
    """Evaluate only the newest settled games and expose useful stability segments."""
    settled = sorted(
        (row for row in rows if row.get("actual_home_win") is not None),
        key=lambda row: str(row.get("game_start") or row.get("generated_at") or ""),
    )
    if not settled:
        return {"method": "chronological_holdout", "training_games": 0, "holdout_games": 0, "metrics": evaluate_game_predictions([]), "segments": []}
    holdout_count = max(1, math.ceil(len(settled) * max(0.1, min(0.5, holdout_fraction))))
    holdout = settled[-holdout_count:]
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in holdout:
        for dimension, value in _segment_values(row).items():
            grouped[(dimension, value)].append(row)
    segments = []
    for (dimension, value), segment_rows in sorted(grouped.items()):
        segments.append({"dimension": dimension, "value": value, **evaluate_game_predictions(segment_rows)})
    return {
        "method": "chronological_holdout",
        "training_games": len(settled) - holdout_count,
        "holdout_games": holdout_count,
        "metrics": evaluate_game_predictions(holdout),
        "segments": segments,
    }


def chronological_model_comparison(
    rows: list[dict],
    candidate_version: str,
    baseline_version: str,
    *,
    holdout_fraction: float = 0.25,
) -> dict:
    """Compare model versions on the same newest settled games only."""
    grouped: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        if row.get("actual_home_win") is None:
            continue
        game_id = str(row.get("game_id") or row.get("game") or "")
        version = str(row.get("model_version") or "")
        if not game_id or version not in {candidate_version, baseline_version}:
            continue
        existing = grouped[game_id].get(version)
        if existing is None or str(row.get("generated_at") or "") > str(existing.get("generated_at") or ""):
            grouped[game_id][version] = row
    paired = [
        versions for versions in grouped.values()
        if candidate_version in versions and baseline_version in versions
    ]
    paired.sort(key=lambda versions: str(versions[candidate_version].get("game_start") or versions[candidate_version].get("generated_at") or ""))
    if not paired:
        return {
            "method": "chronological_paired_holdout",
            "holdout_games": 0,
            "candidate": evaluate_game_predictions([]),
            "baseline": evaluate_game_predictions([]),
            "beats_baseline": False,
        }
    holdout_count = max(1, math.ceil(len(paired) * max(0.1, min(0.5, holdout_fraction))))
    holdout = paired[-holdout_count:]
    candidate_rows = [versions[candidate_version] for versions in holdout]
    baseline_rows = [versions[baseline_version] for versions in holdout]
    candidate = evaluate_game_predictions(candidate_rows)
    baseline = evaluate_game_predictions(baseline_rows)
    candidate_brier = candidate.get("brier_score")
    baseline_brier = baseline.get("brier_score")
    return {
        "method": "chronological_paired_holdout",
        "holdout_games": len(holdout),
        "candidate": candidate,
        "baseline": baseline,
        "beats_baseline": (
            candidate_brier is not None
            and baseline_brier is not None
            and float(candidate_brier) < float(baseline_brier)
        ),
    }


def _confidence_band(row: dict) -> str:
    confidence = abs(float(row.get("home_win_probability") or 0.5) - 0.5) * 2
    if confidence < 0.1:
        return "coin_flip"
    if confidence < 0.25:
        return "lean"
    return "strong_lean"


def _segment_values(row: dict) -> dict[str, str]:
    probability = float(row.get("home_win_probability") or 0.5)
    margin = abs(float(row.get("expected_margin") or 0.0))
    total = float(row.get("expected_total") or 0.0)
    return {
        "sport": str(row.get("sport") or "Unknown"),
        "confidence": _confidence_band(row),
        "favorite_side": "home" if probability >= 0.5 else "away",
        "projected_margin": "close" if margin < 4 else "moderate" if margin < 10 else "wide",
        "market_total": "missing" if total <= 0 else "lower" if total < 45 else "higher",
        "game_script": str(row.get("game_script") or "neutral"),
        "data_quality": str(row.get("data_quality") or "Unknown"),
        "model_version": str(row.get("model_version") or "Unknown"),
    }


def _mae(rows: list[dict], predicted_key: str, actual_key: str) -> float | None:
    pairs = [(float(row[predicted_key]), float(row[actual_key])) for row in rows if row.get(predicted_key) is not None and row.get(actual_key) is not None]
    return round(sum(abs(predicted - actual) for predicted, actual in pairs) / len(pairs), 3) if pairs else None
