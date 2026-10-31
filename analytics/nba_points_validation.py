"""Chronological, read-only validation of locked NBA points forecasts."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from math import isfinite, sqrt
from zoneinfo import ZoneInfo

from analytics.nba_points_minutes import MODEL_VERSION as MINUTES_SHADOW_VERSION
from analytics.nba_points_shot_volume import MODEL_VERSION as SHOT_VOLUME_SHADOW_VERSION
from services.game_team_features import NBA_DEFENSE_CONTEXT_VERSION
from utils.entity_normalization import canonical_person_key

VERIFIED_FINAL_SOURCES = {"espn", "nba_api", "statshawk", "balldontlie"}
NBA_GAME_TIMEZONE = ZoneInfo("America/New_York")


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


def _game_date(value: object) -> str | None:
    stamp = _time(value)
    return stamp.astimezone(NBA_GAME_TIMEZONE).date().isoformat() if stamp else None


def _eligible(row: dict) -> str | None:
    if row.get("legacy_quarantined"):
        return "quarantined"
    if str(row.get("sport") or "").upper() != "NBA" or str(row.get("stat") or "").upper() not in {"POINTS", "PTS"}:
        return "other_market"
    if row.get("outcome_source") not in VERIFIED_FINAL_SOURCES or row.get("result") not in {"Win", "Loss"}:
        return "unverified_final"
    snapshot = row.get("feature_snapshot") or {}
    if isinstance(snapshot, dict) and snapshot.get("source") == "market_prior":
        return "market_prior_only"
    if not isinstance(snapshot, dict) or snapshot.get("source") != "verified_history_distribution":
        return "no_locked_points_forecast"
    if not row.get("independent_market_key") or not row.get("model_version") or "legacy" in str(row["model_version"]).lower():
        return "missing_identity_or_version"
    if not row.get("player_identity_id") and not canonical_person_key(row.get("player")):
        return "missing_player_identity"
    feature_at, predicted, game, settled = (_time(row.get(key)) for key in (
        "feature_as_of", "predicted_at", "game_time", "settled_at",
    ))
    if not all((feature_at, predicted, game, settled)):
        return "not_locked_before_game"
    if feature_at > predicted:
        gap_seconds = (feature_at - predicted).total_seconds()
        if 3 * 3600 <= gap_seconds <= 6 * 3600 and feature_at < game <= settled:
            return "suspected_timestamp_timezone_mismatch"
        return "not_locked_before_game"
    if not predicted < game <= settled:
        return "not_locked_before_game"
    features = snapshot.get("features") or {}
    if not isinstance(features, dict):
        return "no_locked_points_forecast"
    season_end = str(features.get("season_end") or "")[:10]
    game_day = _game_date(game)
    if not game_day:
        return "not_locked_before_game"
    if season_end and season_end >= game_day:
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


def _locked_minutes_projection(features: dict) -> float | None:
    shadow = features.get("nba_points_minutes_shadow")
    if not isinstance(shadow, dict) or shadow.get("model_version") != MINUTES_SHADOW_VERSION:
        return None
    if shadow.get("shadow_only") is not True or shadow.get("status") not in {"awaiting_holdout", "shadow_evaluation"}:
        return None
    sample = _number(shadow.get("sample_size"))
    projection = _number(shadow.get("expected_points"))
    if sample is None or sample < 5 or projection is None or not 0 <= projection <= 100:
        return None
    return projection


def _locked_shot_volume_projection(features: dict) -> float | None:
    shadow = features.get("nba_points_shot_volume_shadow")
    if not isinstance(shadow, dict) or shadow.get("model_version") != SHOT_VOLUME_SHADOW_VERSION:
        return None
    if shadow.get("shadow_only") is not True or shadow.get("status") not in {"awaiting_holdout", "shadow_evaluation"}:
        return None
    sample = _number(shadow.get("sample_size"))
    projection = _number(shadow.get("expected_points"))
    if sample is None or sample < 5 or projection is None or not 0 <= projection <= 100:
        return None
    return projection


def _locked_defense_score(features: dict, row: dict) -> float | None:
    context = features.get("nba_points_opponent_defense")
    if not isinstance(context, dict) or context.get("model_version") != NBA_DEFENSE_CONTEXT_VERSION:
        return None
    if context.get("shadow_only") is not True:
        return None
    captured = _time(context.get("evidence_as_of"))
    predicted = _time(row.get("predicted_at"))
    game = _time(row.get("game_time"))
    score = _number(context.get("advantage_score"))
    sample = _number(context.get("opponent_sample_size"))
    teams = _number(context.get("ranked_teams"))
    if (not all((captured, predicted, game)) or not captured <= predicted < game
            or score is None or not 0 <= score <= 100
            or sample is None or sample < 5 or teams is None or teams < 10):
        return None
    return score


def _chronological_board_holdout(rows: list[dict]) -> dict:
    dates = sorted({row["game_date"] for row in rows})
    if len(rows) < 30 or len(dates) < 5:
        return {
            "status": "insufficient_board_evidence",
            "board_samples": len(rows), "game_dates": len(dates),
            "reason": "At least 30 settled board offers across five game dates are needed for a later-games check.",
        }
    cutoff = dates[int(len(dates) * 0.7)]
    later = [row for row in rows if row["game_date"] >= cutoff]
    if len(later) < 10:
        return {
            "status": "insufficient_later_games",
            "board_samples": len(rows), "game_dates": len(dates),
            "later_samples": len(later), "cutoff_game_date": cutoff,
            "reason": "Fewer than ten independent offers settled in the later-game window.",
        }
    paired_minutes = [row for row in later if row["minutes_shadow_projection"] is not None]
    paired_shot_volume = [row for row in later if row["shot_volume_shadow_projection"] is not None]
    return {
        "status": "exploratory_holdout",
        "board_samples": len(rows), "game_dates": len(dates),
        "cutoff_game_date": cutoff,
        "earlier_samples": len(rows) - len(later),
        "later_samples": len(later),
        "forecast": _metrics(later),
        "exact_line": _baseline(later, "line"),
        "locked_recent_5_mean": _baseline(later, "recent_5_mean"),
        "paired_minutes": {
            "samples": len(paired_minutes),
            "champion": _baseline(paired_minutes, "projection"),
            "minutes_shadow": _baseline(paired_minutes, "minutes_shadow_projection"),
            "exact_line": _baseline(paired_minutes, "line"),
        },
        "paired_shot_volume": {
            "samples": len(paired_shot_volume),
            "champion": _baseline(paired_shot_volume, "projection"),
            "shot_volume_shadow": _baseline(paired_shot_volume, "shot_volume_shadow_projection"),
            "exact_line": _baseline(paired_shot_volume, "line"),
        },
        "promotion_ready": False,
        "reason": "Later-game board evidence is descriptive; neither challenger has a validated exact-line probability.",
    }


def evaluate_nba_points_predictions(rows: list[dict]) -> dict:
    """Use only independently settled offers whose pregame evidence is locked."""
    excluded: Counter[str] = Counter()
    excluded_by_origin: dict[str, Counter[str]] = defaultdict(Counter)
    observed_by_origin: Counter[str] = Counter()
    selected: dict[tuple[str, str, str], dict] = {}
    origin_selected: dict[tuple[str, str, str, str], dict] = {}
    for row in sorted(rows, key=lambda item: _time(item.get("predicted_at")) or datetime.max.replace(tzinfo=UTC)):
        row_origin = str(row.get("evidence_origin") or "placed_entry")
        observed_by_origin[row_origin] += 1
        reason = _eligible(row)
        if reason:
            excluded[reason] += 1
            excluded_by_origin[row_origin][reason] += 1
            continue
        normalized_player = canonical_person_key(row.get("player"))
        player_key = f"name:{normalized_player}" if normalized_player else f"id:{row['player_identity_id']}"
        game_date = _game_date(row["game_time"]) or ""
        key = (str(row["model_version"]), player_key, game_date)
        origin = str(row.get("evidence_origin") or "placed_entry")
        origin_key = (key[0], origin, player_key, game_date)
        snapshot = row["feature_snapshot"]
        features = snapshot.get("features") or {}
        evaluated = {
            **row,
            "actual": float(row["actual"]),
            "line": float(row["line"]),
            "projection": float(row["projection"]),
            "probability": float(row["probability"]),
            "recent_5_mean": _number(features.get("recent_5_mean")),
            "minutes_shadow_projection": _locked_minutes_projection(features),
            "shot_volume_shadow_projection": _locked_shot_volume_projection(features),
            "matchup_indicator": _locked_defense_score(features, row),
            "verified_games": _number(features.get("verified_games")),
            "game_date": game_date,
            "evidence_origin": origin,
        }
        origin_selected.setdefault(origin_key, evaluated)
        if key in selected:
            excluded["duplicate_player_game"] += 1
            excluded_by_origin[row_origin]["duplicate_player_game"] += 1
            continue
        selected[key] = evaluated
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
        origin_metrics = {
            origin: {
                "metrics": _metrics(origin_rows),
                "paired_baselines": {
                    "exact_line": _baseline(origin_rows, "line"),
                    "locked_recent_5_mean": _baseline(origin_rows, "recent_5_mean"),
                    "locked_minutes_shadow": _baseline(origin_rows, "minutes_shadow_projection"),
                    "locked_shot_volume_shadow": _baseline(origin_rows, "shot_volume_shadow_projection"),
                },
            }
            for origin in sorted({key[1] for key in origin_selected if key[0] == version})
            if (origin_rows := [row for key, row in origin_selected.items() if key[0] == version and key[1] == origin])
        }
        matchup_rows = [row for row in version_rows if row["matchup_indicator"] is not None]
        matchup_segments = [
            {"label": label, "indicator_range": [low, high], **_metrics(segment)}
            for label, low, high in (("Lower points allowed", 0, 33), ("Middle", 34, 66), ("Higher points allowed", 67, 100))
            if (segment := [row for row in matchup_rows if low <= row["matchup_indicator"] <= high])
        ]
        versions.append({
            "model_version": version,
            "evidence_origin": next(iter(origin_metrics)) if len(origin_metrics) == 1 else "mixed",
            "by_evidence_origin": origin_metrics,
            "chronological_board_holdout": _chronological_board_holdout([
                row for key, row in origin_selected.items() if key[0] == version and key[1] == "prospective_board"
            ]),
            "first_game": version_rows[0]["game_date"],
            "last_game": version_rows[-1]["game_date"],
            "metrics": _metrics(version_rows),
            "paired_baselines": {
                "exact_line": _baseline(version_rows, "line"),
                "locked_recent_5_mean": _baseline(version_rows, "recent_5_mean"),
                "locked_minutes_shadow": _baseline(version_rows, "minutes_shadow_projection"),
                "locked_shot_volume_shadow": _baseline(version_rows, "shot_volume_shadow_projection"),
            },
            "calibration_buckets": buckets,
            "by_line": thresholds,
            "by_history_size": history_segments,
            "matchup_difficulty": {
                "status": "descriptive_segments" if matchup_rows else "unavailable",
                "samples": len(matchup_rows), "segments": matchup_segments,
                "reason": (
                    "Locked pregame opponent team points-allowed percentiles; selected segments are descriptive, not validated player matchup effects."
                    if matchup_rows else "No versioned, pregame opponent-defense comparison is locked in these records."
                ),
            },
            "promotion_ready": False,
        })
    paired = []
    for version in versions:
        paired_rows = [
            row for row in grouped[version["model_version"]]
            if row["minutes_shadow_projection"] is not None or row["shot_volume_shadow_projection"] is not None
        ]
        if paired_rows:
            minutes_rows = [row for row in paired_rows if row["minutes_shadow_projection"] is not None]
            shot_volume_rows = [row for row in paired_rows if row["shot_volume_shadow_projection"] is not None]
            paired.append({
                "model_version": version["model_version"],
                "samples": len(minutes_rows),
                "champion": _baseline(minutes_rows, "projection"),
                "minutes_shadow": _baseline(minutes_rows, "minutes_shadow_projection"),
                "recent_5_mean": _baseline(minutes_rows, "recent_5_mean"),
                "exact_line": _baseline(minutes_rows, "line"),
                "shot_volume": {
                    "samples": len(shot_volume_rows),
                    "champion": _baseline(shot_volume_rows, "projection"),
                    "shot_volume_shadow": _baseline(shot_volume_rows, "shot_volume_shadow_projection"),
                    "recent_5_mean": _baseline(shot_volume_rows, "recent_5_mean"),
                    "exact_line": _baseline(shot_volume_rows, "line"),
                },
            })
    independent_player_games = {(key[1], key[2]) for key in selected}
    origin_counts = {
        origin: len({(key[2], key[3]) for key in origin_selected if key[1] == origin})
        for origin in {key[1] for key in origin_selected}
    }
    return {
        "status": "evidence_available" if versions else "insufficient_locked_evidence",
        "examined": len(rows),
        "eligible_independent": len(independent_player_games),
        "evidence_origins": origin_counts,
        "evidence_maturity": "exploratory" if len(independent_player_games) < 100 else "initial_evaluation",
        "excluded": dict(sorted(excluded.items())),
        "observed_settled_by_origin": dict(sorted(observed_by_origin.items())),
        "excluded_by_origin": {
            origin: dict(sorted(counts.items())) for origin, counts in sorted(excluded_by_origin.items())
        },
        "versions": versions,
        "challenger_comparison": {
            "status": "paired_exploratory" if paired else "not_paired",
            "versions": paired,
            "reason": (
                "Paired pregame minutes and shot-volume estimates can be compared with the current forecast on the same settled offers. "
                "Neither challenger has a calibrated probability, so projection error alone cannot authorize promotion."
                if paired else
                "The NBA points challenger has no paired, locked pregame outcomes yet; it cannot be promoted from this report."
            ),
        },
        "ev": None,
        "note": "Read-only chronological evaluation. The same settled offers are used for model and line baselines; market line is not a no-vig probability.",
    }
