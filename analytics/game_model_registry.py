from __future__ import annotations

GAME_MARKET_CHAMPION_VERSION = "game-market-baseline-v1"
GAME_HISTORICAL_BASELINE_VERSION = "game-historical-baseline-v1"
GAME_CONTEXT_CHALLENGER_VERSION = "edgeiq-game-context-v1"
GAME_AWARE_PROP_CHALLENGER_VERSION = "edgeiq-game-context-prop-distribution-v2.5.0"


def game_model_registry() -> dict:
    return {
        "paid_mode": "champion_only",
        "models": [
            {"version": GAME_MARKET_CHAMPION_VERSION, "role": "champion", "paid_eligible": False},
            {"version": GAME_HISTORICAL_BASELINE_VERSION, "role": "baseline", "paid_eligible": False},
            {
                "version": GAME_CONTEXT_CHALLENGER_VERSION,
                "role": "challenger",
                "paid_eligible": False,
                "reason": "Shadow-only until chronological evaluation beats both market and historical baselines.",
            },
            {
                "version": GAME_AWARE_PROP_CHALLENGER_VERSION,
                "role": "prop_challenger",
                "paid_eligible": False,
                "reason": "Game context may alter opportunity assumptions only; it cannot directly change confidence.",
            },
        ],
        "promotion_requirements": {
            "minimum_settled_games": 200,
            "maximum_brier": 0.20,
            "maximum_calibration_gap_points": 7.5,
            "chronological_holdout_required": True,
            "must_beat_market_baseline": True,
            "must_beat_historical_baseline": True,
        },
    }


def promotion_decision(metrics: dict) -> dict:
    gates = game_model_registry()["promotion_requirements"]
    checks = {
        "sample": int(metrics.get("settled_games") or 0) >= gates["minimum_settled_games"],
        "brier": float(metrics.get("brier_score") or 1.0) <= gates["maximum_brier"],
        "calibration": abs(float(metrics.get("calibration_gap") or 100.0)) <= gates["maximum_calibration_gap_points"],
        "chronological": bool(metrics.get("chronological_holdout")),
        "market": bool(metrics.get("beats_market_baseline")),
        "historical": bool(metrics.get("beats_historical_baseline")),
    }
    return {"promotable": all(checks.values()), "checks": checks, "requirements": gates}
