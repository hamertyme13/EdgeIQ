from __future__ import annotations

import math
from collections import defaultdict


def evaluate_game_predictions(rows: list[dict]) -> dict:
    settled = [row for row in rows if row.get("actual_home_win") is not None]
    if not settled:
        return {"settled_games": 0, "brier_score": None, "log_loss": None, "accuracy": None, "calibration_gap": None, "buckets": []}
    probabilities = [max(0.001, min(0.999, float(row["home_win_probability"]))) for row in settled]
    outcomes = [float(row["actual_home_win"]) for row in settled]
    brier = sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes, strict=False)) / len(settled)
    log_loss = -sum(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability) for probability, outcome in zip(probabilities, outcomes, strict=False)) / len(settled)
    accuracy = sum((probability >= 0.5) == bool(outcome) for probability, outcome in zip(probabilities, outcomes, strict=False)) / len(settled)
    buckets = []
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
