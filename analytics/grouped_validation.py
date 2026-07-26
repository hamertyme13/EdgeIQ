from __future__ import annotations

import math

from analytics.prediction_evidence import deduplicate_outcomes


def grouped_rolling_validation(
    rows: list[dict],
    *,
    minimum_train: int = 100,
    minimum_predictions: int = 30,
) -> dict:
    eligible = [
        row for row in deduplicate_outcomes(rows)
        if row.get("result") in {"Win", "Loss"}
        and row.get("probability") is not None
        and not row.get("legacy_quarantined")
    ]
    eligible.sort(key=_time_key)
    predictions: list[dict] = []

    for target in eligible:
        target_time = _time_key(target)
        train = [
            row for row in eligible
            if _truth_time(row) and _truth_time(row) < target_time
        ]
        if len(train) < minimum_train:
            continue
        raw = _probability(target)
        calibrated, peers = _fit_prior_only_calibration(raw, target, train)
        actual = 1.0 if target["result"] == "Win" else 0.0
        predictions.append({
            "market_key": target.get("independent_market_key", ""),
            "game_group": _game_group(target),
            "raw": raw,
            "predicted": calibrated,
            "actual": actual,
            "peer_count": peers,
        })

    if len(predictions) < minimum_predictions:
        return {
            "ready": False,
            "passed": False,
            "unique_predictions": len(eligible),
            "evaluated_predictions": len(predictions),
            "minimum_train": minimum_train,
            "minimum_predictions": minimum_predictions,
            "leakage_free": True,
            "message": (
                f"Collect {minimum_predictions} rolling predictions after a {minimum_train}-result training window."
            ),
        }

    brier = sum((row["predicted"] - row["actual"]) ** 2 for row in predictions) / len(predictions)
    raw_brier = sum((row["raw"] - row["actual"]) ** 2 for row in predictions) / len(predictions)
    baseline_brier = sum((0.5 - row["actual"]) ** 2 for row in predictions) / len(predictions)
    log_loss = _log_loss(predictions)
    baseline_log_loss = -math.log(0.5)
    ece = _expected_calibration_error(predictions)
    differences = [
        ((row["predicted"] - row["actual"]) ** 2) - ((0.5 - row["actual"]) ** 2)
        for row in predictions
    ]
    mean_difference = sum(differences) / len(differences)
    standard_error = _standard_error(differences)
    upper_95 = mean_difference + 1.96 * standard_error
    passed = brier < baseline_brier and log_loss < baseline_log_loss and ece <= 0.08 and upper_95 < 0
    return {
        "ready": True,
        "passed": passed,
        "unique_predictions": len(eligible),
        "evaluated_predictions": len(predictions),
        "game_groups": len({_game_group(row) for row in eligible}),
        "minimum_train": minimum_train,
        "leakage_free": True,
        "brier_score": round(brier, 4),
        "raw_brier_score": round(raw_brier, 4),
        "baseline_brier_score": round(baseline_brier, 4),
        "log_loss": round(log_loss, 4),
        "baseline_log_loss": round(baseline_log_loss, 4),
        "expected_calibration_error": round(ece * 100.0, 2),
        "brier_lift_vs_baseline": round((baseline_brier - brier) * 100.0, 2),
        "lift_upper_95": round(-upper_95 * 100.0, 2),
        "message": (
            "Versioned predictions beat the neutral baseline out of sample with a positive confidence bound."
            if passed
            else "Versioned predictions have not yet proven out-of-sample lift; keep paid mode restricted."
        ),
    }


def _fit_prior_only_calibration(raw: float, target: dict, train: list[dict]) -> tuple[float, int]:
    peers = [
        row for row in train
        if str(row.get("sport") or "").upper() == str(target.get("sport") or "").upper()
        and str(row.get("stat") or "").lower() == str(target.get("stat") or "").lower()
        and str(row.get("direction") or "").lower() == str(target.get("direction") or "").lower()
    ]
    if len(peers) < 20:
        peers = [
            row for row in train
            if str(row.get("sport") or "").upper() == str(target.get("sport") or "").upper()
        ]
    wins = sum(1 for row in peers if row.get("result") == "Win")
    prior_strength = 30.0
    posterior = ((raw * prior_strength) + wins) / (prior_strength + len(peers))
    return max(0.02, min(0.98, posterior)), len(peers)


def _expected_calibration_error(rows: list[dict]) -> float:
    total = len(rows)
    buckets: dict[float, list[dict]] = {}
    for row in rows:
        bucket_key = round(row["predicted"] * 20) / 20
        buckets.setdefault(bucket_key, []).append(row)
    error = 0.0
    for bucket in buckets.values():
        predicted = sum(row["predicted"] for row in bucket) / len(bucket)
        actual = sum(row["actual"] for row in bucket) / len(bucket)
        error += len(bucket) / total * abs(actual - predicted)
    return error


def _log_loss(rows: list[dict]) -> float:
    losses = []
    for row in rows:
        probability = max(0.001, min(0.999, row["predicted"]))
        losses.append(-(row["actual"] * math.log(probability) + (1 - row["actual"]) * math.log(1 - probability)))
    return sum(losses) / len(losses)


def _standard_error(values: list[float]) -> float:
    if len(values) < 2:
        return float("inf")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance / len(values))


def _probability(row: dict) -> float:
    return max(0.02, min(0.98, float(row.get("probability") or row.get("predicted") or 50.0) / 100.0))


def _time_key(row: dict) -> str:
    return str(row.get("predicted_at") or row.get("placed_at") or row.get("game_time") or "")


def _truth_time(row: dict) -> str:
    return str(row.get("settled_at") or "")


def _game_group(row: dict) -> str:
    return str(row.get("game") or row.get("independent_market_key") or "")
