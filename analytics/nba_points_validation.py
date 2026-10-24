"""Chronological, read-only validation of locked NBA points forecasts."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from math import isfinite, sqrt

VERIFIED_FINAL_SOURCES = {"espn", "nba_api", "statshawk", "balldontlie"}


def _time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _eligible(row: dict) -> str | None:
    if row.get("legacy_quarantined"):
        return "quarantined"
    if str(row.get("sport") or "").upper() != "NBA" or str(row.get("stat") or "").upper() not in {"POINTS", "PTS"}:
        return "other_market"
    if row.get("outcome_source") not in VERIFIED_FINAL_SOURCES or row.get("result") not in {"Win", "Loss"}:
        return "unverified_final"
    snapshot = row.get("feature_snapshot") or {}
    if not isinstance(snapshot, dict) or snapshot.get("source") != "verified_history_distribution":
        return "no_locked_points_forecast"
    if not row.get("independent_market_key") or not row.get("model_version") or "legacy" in str(row["model_version"]).lower():
        return "missing_identity_or_version"
    feature_at, predicted, game, settled = (_time(row.get(key)) for key in (
        "feature_as_of", "predicted_at", "game_time", "settled_at",
    ))
    if not all((feature_at, predicted, game, settled)) or not feature_at <= predicted < game <= settled:
        return "not_locked_before_game"
    features = snapshot.get("features") or {}
    if not isinstance(features, dict):
        return "no_locked_points_forecast"
    season_end = str(features.get("season_end") or "")[:10]
    if season_end and season_end >= game.date().isoformat():
        return "postgame_history"
    actual, line, projection, probability = (_number(row.get(key)) for key in (
        "actual", "line", "projection", "probability",
    ))
    if any(value is None for value in (actual, line, projection, probability)) or not 0 <= probability <= 100:
        return "invalid_number"
    if actual == line or row.get("direction") not in {"Over", "Under"}:
        return "push_or_direction"
    expected = "Win" if (actual > line) == (row["direction"] == "Over") else "Loss"
    if row["result"] != expected:
        return "conflicting_result"
    return None


def _metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"samples": 0, "mae": None, "rmse": None, "brier": None, "calibration_gap_points": None}
    errors = [row["projection"] - row["actual"] for row in rows]
    brier = [((row["probability"] / 100) - (row["result"] == "Win")) ** 2 for row in rows]
    predicted_rate = sum(row["probability"] for row in rows) / len(rows)
    actual_rate = 100 * sum(row["result"] == "Win" for row in rows) / len(rows)
    return {
        "samples": len(rows),
        "mae": round(sum(abs(error) for error in errors) / len(errors), 3),
        "rmse": round(sqrt(sum(error * error for error in errors) / len(errors)), 3),
        "brier": round(sum(brier) / len(brier), 4),
        "predicted_hit_rate": round(predicted_rate, 1),
        "actual_hit_rate": round(actual_rate, 1),
        "calibration_gap_points": round(actual_rate - predicted_rate, 1),
    }


def _baseline(rows: list[dict], key: str) -> dict:
    pairs = [(row["actual"], _number(row[key])) for row in rows]
    errors = [prediction - actual for actual, prediction in pairs if prediction is not None]
    return {
        "samples": len(errors),
        "mae": round(sum(abs(error) for error in errors) / len(errors), 3) if errors else None,
        "rmse": round(sqrt(sum(error * error for error in errors) / len(errors)), 3) if errors else None,
    }


def evaluate_nba_points_predictions(rows: list[dict]) -> dict:
    """Use only independently settled offers whose pregame evidence is locked."""
    excluded: Counter[str] = Counter()
    selected: dict[tuple[str, str], dict] = {}
    for row in sorted(rows, key=lambda item: _time(item.get("predicted_at")) or datetime.max.replace(tzinfo=UTC)):
        reason = _eligible(row)
        if reason:
            excluded[reason] += 1
            continue
        key = (str(row["model_version"]), str(row["independent_market_key"]))
        if key in selected:
            excluded["duplicate_market"] += 1
            continue
        snapshot = row["feature_snapshot"]
        features = snapshot.get("features") or {}
        selected[key] = {
            **row,
            "actual": float(row["actual"]),
            "line": float(row["line"]),
            "projection": float(row["projection"]),
            "probability": float(row["probability"]),
            "recent_5_mean": _number(features.get("recent_5_mean")),
            "verified_games": _number(features.get("verified_games")),
            "game_date": _time(row["game_time"]).date().isoformat(),
        }
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in selected.values():
        grouped[row["model_version"]].append(row)
    versions = []
    for version, version_rows in sorted(grouped.items()):
        version_rows.sort(key=lambda item: (item["game_date"], str(item["independent_market_key"])))
        buckets = []
        for low in range(0, 100, 10):
            segment = [row for row in version_rows if low <= row["probability"] < low + 10 or low == 90 and row["probability"] == 100]
            if segment:
                buckets.append({"label": f"{low}-{low + 10}%", **_metrics(segment)})
        thresholds = []
        for label, low, high in (("Under 15", 0, 15), ("15-24.5", 15, 25), ("25-34.5", 25, 35), ("35+", 35, float("inf"))):
            segment = [row for row in version_rows if low <= row["line"] < high]
            if segment:
                thresholds.append({"label": label, **_metrics(segment)})
        history_segments = []
        for label, low, high in (("Under 10", 0, 10), ("10-19", 10, 20), ("20+", 20, float("inf"))):
            segment = [row for row in version_rows if row["verified_games"] is not None and low <= row["verified_games"] < high]
            if segment:
                history_segments.append({"label": label, **_metrics(segment)})
        versions.append({
            "model_version": version,
            "first_game": version_rows[0]["game_date"],
            "last_game": version_rows[-1]["game_date"],
            "metrics": _metrics(version_rows),
            "paired_baselines": {
                "exact_line": _baseline(version_rows, "line"),
                "locked_recent_5_mean": _baseline(version_rows, "recent_5_mean"),
            },
            "calibration_buckets": buckets,
            "by_line": thresholds,
            "by_history_size": history_segments,
            "matchup_difficulty": {"status": "unavailable", "reason": "No versioned, pregame opponent-difficulty feature is locked in these records."},
            "promotion_ready": False,
        })
    return {
        "status": "evidence_available" if versions else "insufficient_locked_evidence",
        "examined": len(rows),
        "eligible_independent": len(selected),
        "evidence_maturity": "exploratory" if len(selected) < 100 else "initial_evaluation",
        "excluded": dict(sorted(excluded.items())),
        "versions": versions,
        "challenger_comparison": {
            "status": "not_paired",
            "reason": "The NBA points challenger has no paired, locked pregame probability ledger yet; it cannot be promoted from this report.",
        },
        "ev": None,
        "note": "Read-only chronological evaluation. The same settled offers are used for model and line baselines; market line is not a no-vig probability.",
    }
