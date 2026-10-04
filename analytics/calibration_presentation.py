from __future__ import annotations

_TIER_LABELS = {
    "sport_stat_provider_direction_source": "same sport, stat, provider, direction, and projection source",
    "sport_stat_provider_direction": "same sport, stat, provider, and direction",
    "sport_stat_direction": "same sport, stat, and direction",
    "sport_stat": "same sport and stat",
    "sport": "sport-wide fallback",
}


def calibration_presentation(calibration: dict | None) -> dict:
    """Describe the evidence behind displayed confidence without inventing validation metrics."""
    if not calibration:
        return {
            "status": "UNAVAILABLE", "label": "Calibration unavailable",
            "model_probability": None, "display_probability": None,
            "calibrated_probability": None, "sample_size": 0,
            "segment_sample_size": 0, "basis": "No versioned calibration snapshot",
            "uncertainty_points": None, "calibration_error": None, "brier_score": None,
        }
    tier = str(calibration.get("tier") or "uncalibrated")
    samples = max(0, int(calibration.get("sample_size") or 0))
    segment_samples = max(0, int(calibration.get("segment_sample_size") or 0))
    uncertainty = calibration.get("uncertainty_points")
    uncertainty = float(uncertainty) if uncertainty is not None else None
    if tier == "uncalibrated" or samples == 0:
        status, label = "INSUFFICIENT_SAMPLE", "Insufficient calibration history"
    elif uncertainty is not None and uncertainty > 10:
        status, label = "DEGRADED", "Calibration uncertainty is high"
    elif segment_samples < 100 or samples < 100:
        status, label = "PARTIAL", "Partial calibration evidence"
    else:
        status, label = "CALIBRATED", "Calibrated with settled outcomes"
    return {
        "status": status,
        "label": label,
        "model_probability": calibration.get("raw_probability"),
        "display_probability": calibration.get("probability"),
        "calibrated_probability": calibration.get("probability") if tier != "uncalibrated" and samples else None,
        "sample_size": samples,
        "segment_sample_size": segment_samples,
        "basis": _TIER_LABELS.get(tier, "Insufficient matching history"),
        "uncertainty_points": uncertainty if tier != "uncalibrated" else None,
        "calibration_error": None,
        "brier_score": None,
    }
