"""Exploratory same-offer projection-error comparisons with date-block uncertainty."""

from __future__ import annotations

from collections import defaultdict
from datetime import date as calendar_date
from math import isfinite
from random import Random


def paired_error_evidence(
    rows: list[dict], candidate_key: str, baseline_key: str,
    *, minimum_samples: int = 30, minimum_dates: int = 5,
) -> dict:
    paired: list[tuple[str, float, float]] = []
    for row in rows:
        if row.get("history_provenance_status") != "verified":
            continue
        try:
            actual = float(row["actual"])
            candidate = float(row[candidate_key])
            baseline = float(row[baseline_key])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        game_date = str(row.get("game_date") or "")
        try:
            game_date = calendar_date.fromisoformat(game_date).isoformat()
        except ValueError:
            continue
        if not all(isfinite(value) and 0 <= value <= 100 for value in (actual, candidate, baseline)):
            continue
        paired.append((game_date, abs(candidate - actual), abs(baseline - actual)))

    date_differences: dict[str, list[float]] = defaultdict(list)
    for game_date, candidate_error, baseline_error in paired:
        date_differences[game_date].append(baseline_error - candidate_error)
    result = {
        "status": "insufficient_paired_evidence",
        "samples": len(paired), "game_dates": len(date_differences),
        "minimum_samples": minimum_samples, "minimum_dates": minimum_dates,
        "candidate_mae": None, "baseline_mae": None,
        "mae_advantage_points": None, "date_block_interval_95": None,
        "promotion_ready": False,
        "note": "Exploratory paired projection error only; no calibrated probability or promotion decision.",
    }
    if len(paired) < minimum_samples or len(date_differences) < minimum_dates:
        return result

    date_blocks = [(sum(values), len(values)) for _, values in sorted(date_differences.items())]
    random = Random(1937)
    replicates = []
    for _ in range(1000):
        sampled = [date_blocks[random.randrange(len(date_blocks))] for _ in date_blocks]
        replicates.append(sum(total for total, _count in sampled) / sum(count for _total, count in sampled))
    replicates.sort()
    candidate_mae = sum(candidate for _, candidate, _ in paired) / len(paired)
    baseline_mae = sum(baseline for _, _, baseline in paired) / len(paired)
    return {
        **result,
        "status": "exploratory_paired_comparison",
        "candidate_mae": round(candidate_mae, 3),
        "baseline_mae": round(baseline_mae, 3),
        "mae_advantage_points": round(baseline_mae - candidate_mae, 3),
        "date_block_interval_95": [round(replicates[25], 3), round(replicates[974], 3)],
        "note": "Same-offer MAE advantage (positive favors challenger). The interval resamples whole game-date blocks, preserving offer counts within each date; exploratory only and not a promotion decision.",
    }
