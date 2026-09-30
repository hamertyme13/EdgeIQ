"""Chronological, independent evaluation of immutable leg evidence."""
from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

VERIFIED_FINAL_SOURCES = {
    "espn", "espn_official_scoreboard", "mlb_statsapi", "nba_api",
    "pandascore_verified", "statshawk",
}


def _time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _qualified(row: dict) -> tuple[dict | None, str]:
    source = str(row.get("outcome_source") or "").lower()
    if source not in VERIFIED_FINAL_SOURCES:
        return None, "unverified_final_source"
    feature, created, game = (_time(row.get(key)) for key in ("feature_as_of", "created_at", "game_start"))
    if not feature or not created or not game or not feature <= created < game:
        return None, "missing_or_postgame_features"
    if game.astimezone(ZoneInfo("America/New_York")).date().isoformat() != str(row.get("final_game_date") or ""):
        return None, "wrong_game_date"
    try:
        confidence = float(row["confidence"])
        actual = float(row["actual"])
        line = float(row["line"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, "missing_probability_or_final"
    if not all(math.isfinite(value) for value in (confidence, actual, line)) or not 0 <= confidence <= 100:
        return None, "invalid_probability_or_final"
    if row.get("board_outcome") == "Push" or actual == line:
        return None, "push"
    direction = str(row.get("direction") or "")
    if direction not in {"Over", "Under"}:
        return None, "invalid_direction"
    if not row.get("player_key") or not row.get("model_version") or not row.get("stat"):
        return None, "missing_identity"
    win = (actual > line) == (direction == "Over")
    return {
        **row, "probability": confidence / 100.0, "outcome": float(win),
        "game_at": game, "created_at_parsed": created,
        "market_probability": _market_probability(row, created, game, line, direction),
    }, ""


def _market_probability(row: dict, created: datetime, game: datetime, line: float, direction: str) -> float | None:
    baseline = row.get("market_baseline") or {}
    if not isinstance(baseline, dict) or baseline.get("source") != "The Odds API exact-line no-vig":
        return None
    if baseline.get("direction") != direction or not baseline.get("event_id"):
        return None
    observed = _time(baseline.get("observed_at"))
    if not observed or not observed <= created < game or created - observed > timedelta(minutes=30):
        return None
    try:
        books = int(baseline["book_count"])
        baseline_line = float(baseline["line"])
        probability = float(baseline["probability"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if books < 2 or not math.isclose(baseline_line, line, abs_tol=1e-6) or not math.isfinite(probability):
        return None
    return probability / 100.0 if 0 < probability < 100 else None


def _metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"samples": 0, "brier_score": None, "neutral_brier": None, "calibration_error": None,
                "predicted_hit_rate": None, "actual_hit_rate": None}
    count = len(rows)
    brier = sum((row["probability"] - row["outcome"]) ** 2 for row in rows) / count
    predicted = sum(row["probability"] for row in rows) / count
    actual = sum(row["outcome"] for row in rows) / count
    buckets: dict[int, list[dict]] = {}
    for row in rows:
        buckets.setdefault(min(9, int(row["probability"] * 10)), []).append(row)
    error = sum(
        len(bucket) / count * abs(
            sum(row["probability"] for row in bucket) / len(bucket)
            - sum(row["outcome"] for row in bucket) / len(bucket)
        ) for bucket in buckets.values()
    )
    return {
        "samples": count, "brier_score": round(brier, 4), "neutral_brier": 0.25,
        "calibration_error": round(error, 4),
        "predicted_hit_rate": round(predicted * 100, 1),
        "actual_hit_rate": round(actual * 100, 1),
    }


def evaluate_linked_offers(rows: list[dict], *, settled_board_offers: int = 0, truncated: bool = False) -> dict:
    exclusions: Counter[str] = Counter()
    qualified = []
    for row in rows:
        valid, reason = _qualified(row)
        if valid is None:
            exclusions[reason] += 1
        else:
            qualified.append(valid)
    qualified.sort(key=lambda row: (row["game_at"], row["created_at_parsed"], row.get("snapshot_id", "")))
    unique: dict[tuple, dict] = {}
    for row in qualified:
        key = (
            row["model_version"], row["player_key"], row.get("sport"),
            row["final_game_date"], row.get("game"), row["stat"], row["direction"],
        )
        if key in unique:
            exclusions["correlated_duplicate"] += 1
        else:
            unique[key] = row
    by_version: dict[str, list[dict]] = {}
    for row in unique.values():
        by_version.setdefault(row["model_version"], []).append(row)
    sporting_outcomes = {key[1:] for key in unique}
    versions = []
    for version, selected in sorted(by_version.items()):
        selected.sort(key=lambda row: row["game_at"])
        split = int(len(selected) * 0.75)
        if 0 < split < len(selected):
            boundary_day = selected[split]["final_game_date"]
            while split > 0 and selected[split - 1]["final_game_date"] == boundary_day:
                split -= 1
        train, holdout = selected[:split], selected[split:]
        holdout_metrics = _metrics(holdout)
        enough = len(train) >= 70 and len(holdout) >= 30 and not truncated
        neutral_passed = bool(
            enough and holdout_metrics["brier_score"] is not None
            and holdout_metrics["brier_score"] < holdout_metrics["neutral_brier"]
            and holdout_metrics["calibration_error"] <= 0.08
        )
        paired = [row for row in holdout if row["market_probability"] is not None]
        paired_model = _metrics(paired)
        market_brier = (
            sum((row["market_probability"] - row["outcome"]) ** 2 for row in paired) / len(paired)
            if paired else None
        )
        market_ready = len(paired) >= 30 and not truncated
        market_passed = bool(
            market_ready and paired_model["brier_score"] is not None
            and market_brier is not None and paired_model["brier_score"] < market_brier
        )
        segments: dict[tuple[str, str, str], list[dict]] = {}
        for row in selected:
            segments.setdefault((row.get("sport", ""), row["stat"], row.get("provider", "")), []).append(row)
        versions.append({
            "model_version": version, "all": _metrics(selected), "training": _metrics(train),
            "holdout": holdout_metrics, "holdout_ready": enough,
            "neutral_gate_passed": neutral_passed,
            "market_comparison": {
                "paired_samples": len(paired), "model_brier": paired_model["brier_score"],
                "market_brier": round(market_brier, 4) if market_brier is not None else None,
                "ready": market_ready, "passed": market_passed,
            },
            "review_gate_passed": neutral_passed and market_passed,
            "paid_release_approved": False,
            "segments": [
                {"sport": sport, "stat": stat, "provider": provider,
                 **_metrics(segment), "evidence_tier": "initial" if len(segment) >= 100 else "thin"}
                for (sport, stat, provider), segment in sorted(segments.items())
            ],
        })
    return {
        "method": "linked_offer_chronological_holdout", "rows_examined": len(rows),
        "independent_settled_legs": len(sporting_outcomes),
        "versioned_decisions": len(unique), "settled_board_offers": settled_board_offers,
        "coverage_note": "Board count includes recommended and rejected offers; only pregame scored recommendations enter Brier metrics.",
        "baseline_note": "Neutral 50% and captured exact-line no-vig prices are separate; market comparison uses only paired pregame evidence.",
        "exclusions": dict(sorted(exclusions.items())), "truncated": truncated,
        "versions": versions, "automatic_promotion": False,
    }
