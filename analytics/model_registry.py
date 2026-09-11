from __future__ import annotations

PRODUCT_MODEL_VERSION = "edgeiq-champion-router-v2.4.3"
OPPORTUNITY_CHALLENGER_VERSION = "edgeiq-opportunity-aware-distribution-v2.4.3"
HISTORICAL_CHAMPION_VERSION = "edgeiq-historical-distribution-v2.3.1"
SEASON_BASELINE_VERSION = "edgeiq-season-average-baseline-v1"
RECENT_BASELINE_VERSION = "edgeiq-recent-10-baseline-v1"
MARKET_BASELINE_VERSION = "edgeiq-market-line-baseline-v1"


def model_registry() -> dict:
    return {
        "router_version": PRODUCT_MODEL_VERSION,
        "paid_mode": "champion_only",
        "models": [
            {
                "version": HISTORICAL_CHAMPION_VERSION,
                "role": "champion",
                "paid_eligible": True,
                "reason": "Best sufficiently sampled EdgeIQ model by settled Brier score.",
            },
            {
                "version": OPPORTUNITY_CHALLENGER_VERSION,
                "role": "challenger",
                "paid_eligible": False,
                "reason": "Remains shadow-only until it beats the champion and simple baselines.",
            },
            {
                "version": SEASON_BASELINE_VERSION,
                "role": "fallback",
                "paid_eligible": True,
                "reason": "Used when chronological history shows the baseline is more reliable.",
            },
            {
                "version": RECENT_BASELINE_VERSION,
                "role": "fallback",
                "paid_eligible": True,
                "reason": "Used when recent form beats the full-season baseline chronologically.",
            },
            {
                "version": MARKET_BASELINE_VERSION,
                "role": "safety_fallback",
                "paid_eligible": False,
                "reason": "Returns a neutral forecast when verified evidence is insufficient.",
            },
        ],
        "promotion_requirements": {
            "minimum_settled": 200,
            "maximum_brier": 0.20,
            "maximum_calibration_gap_points": 7.5,
            "must_beat_champion": True,
            "must_beat_simple_baseline": True,
            "chronological_holdout_required": True,
        },
    }
