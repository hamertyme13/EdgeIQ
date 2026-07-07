"""
Model calibration.

Measures how well your projected win probabilities match your actual results.
A well-calibrated model: when you say 60%, you should win ~60% of the time.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CalibrationBucket:
    label:          str     # e.g. "50–60%"
    predicted_low:  float
    predicted_high: float
    bets:           int
    wins:           int
    actual_pct:     float   # wins / bets
    predicted_mid:  float   # midpoint of the bucket
    error:          float   # actual_pct - predicted_mid (positive = better than predicted)


def calibrate(bets_with_probs: list[dict]) -> list[CalibrationBucket]:
    """
    Group bets into probability buckets and measure actual vs predicted hit rate.

    Args:
        bets_with_probs: list of dicts with keys:
            'win_probability'  (float 0–100, your estimated prob at bet time)
            'result'           ('Win' | 'Loss' | 'Push')

    Returns:
        List of CalibrationBucket, one per 10-point probability band.
        Buckets with zero bets are omitted.
    """
    buckets_raw: dict[int, dict] = {}

    for bet in bets_with_probs:
        prob = bet.get("win_probability")
        result = bet.get("result", "")
        if prob is None or result == "Push":
            continue

        # Which 10-point bucket?
        bucket_floor = int(prob // 10) * 10
        bucket_floor = max(0, min(90, bucket_floor))

        if bucket_floor not in buckets_raw:
            buckets_raw[bucket_floor] = {"bets": 0, "wins": 0}

        buckets_raw[bucket_floor]["bets"] += 1
        if result == "Win":
            buckets_raw[bucket_floor]["wins"] += 1

    result_buckets = []
    for floor in sorted(buckets_raw.keys()):
        data = buckets_raw[floor]
        n    = data["bets"]
        wins = data["wins"]
        mid  = floor + 5.0
        actual = (wins / n * 100) if n else 0.0

        result_buckets.append(CalibrationBucket(
            label         = f"{floor}–{floor+10}%",
            predicted_low = float(floor),
            predicted_high= float(floor + 10),
            bets          = n,
            wins          = wins,
            actual_pct    = actual,
            predicted_mid = mid,
            error         = actual - mid,
        ))

    return result_buckets
