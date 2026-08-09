from __future__ import annotations

from analytics.prediction_evidence import deduplicate_outcomes


def calibrate_probability(
    raw_probability: float,
    *,
    sport: str,
    stat: str,
    provider: str,
    direction: str,
    projection_source: str,
    rows: list[dict],
) -> dict:
    raw = max(0.02, min(0.98, float(raw_probability)))
    unique_rows = deduplicate_outcomes(rows)
    tiers = (
        (
            "sport_stat_provider_direction_source",
            ("sport", "stat", "platform", "direction", "projection_source"),
            20,
        ),
        ("sport_stat_provider_direction", ("sport", "stat", "platform", "direction"), 20),
        ("sport_stat_direction", ("sport", "stat", "direction"), 35),
        ("sport_stat", ("sport", "stat"), 50),
        ("sport", ("sport",), 100),
    )
    target = {
        "sport": sport.upper(),
        "stat": stat.lower(),
        "platform": provider.lower(),
        "direction": direction.lower(),
        "projection_source": projection_source.lower(),
    }

    for tier, fields, minimum in tiers:
        peers = [row for row in unique_rows if _matches(row, target, fields)]
        if len(peers) < minimum:
            continue
        wins = sum(1 for row in peers if row.get("result") == "Win")
        prior_strength = max(20.0, minimum / 2)
        posterior = ((raw * prior_strength) + wins) / (prior_strength + len(peers))
        uncertainty = 1.96 * ((posterior * (1.0 - posterior) / (prior_strength + len(peers))) ** 0.5)
        cap = 0.90 if len(peers) >= 200 and uncertainty <= 0.07 else 0.84 if len(peers) >= 100 else 0.79
        calibrated = max(0.02, min(cap, posterior))
        return {
            "probability": round(calibrated * 100.0, 2),
            "raw_probability": round(raw * 100.0, 2),
            "tier": tier,
            "sample_size": len(peers),
            "uncertainty_points": round(uncertainty * 100.0, 2),
            "paid_eligible": len(peers) >= minimum and uncertainty <= 0.10,
            "confidence_cap": round(cap * 100.0, 1),
            "cap_reason": "Confidence is capped until this segment has enough precise independent outcomes.",
        }

    cap = 0.69
    return {
        "probability": round(min(raw, cap) * 100.0, 2),
        "raw_probability": round(raw * 100.0, 2),
        "tier": "uncalibrated",
        "sample_size": 0,
        "uncertainty_points": 50.0,
        "paid_eligible": False,
        "confidence_cap": cap * 100.0,
        "cap_reason": "Uncalibrated predictions cannot exceed 69% confidence.",
    }


def _matches(row: dict, target: dict, fields: tuple[str, ...]) -> bool:
    for field in fields:
        observed = str(row.get(field) or "").strip().lower()
        if observed != target[field]:
            return False
    return True
