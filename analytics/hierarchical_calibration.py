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
    unique_rows = deduplicate_outcomes([
        row for row in rows
        if not row.get("legacy_quarantined")
        and row.get("result") in {"Win", "Loss"}
        and str(row.get("outcome_source") or "").strip().lower()
        not in {"", "unknown", "unmatched", "projection_estimate", "integrity_quarantine"}
    ])
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
        "sport": sport.strip().lower(),
        "stat": stat.lower(),
        "platform": provider.lower(),
        "direction": direction.lower(),
        "projection_source": projection_source.lower(),
    }
    segment_peers = [
        row for row in unique_rows
        if _matches(row, target, ("sport", "stat", "platform"))
    ]
    segment_samples = len(segment_peers)
    maturity = (
        "mature" if segment_samples >= 500
        else "developing" if segment_samples >= 200
        else "calibrated" if segment_samples >= 100
        else "thin"
    )

    for tier, fields, minimum in tiers:
        peers = [row for row in unique_rows if _matches(row, target, fields)]
        if len(peers) < minimum:
            continue
        wins = sum(1 for row in peers if row.get("result") == "Win")
        prior_strength = max(20.0, minimum / 2)
        posterior = ((raw * prior_strength) + wins) / (prior_strength + len(peers))
        uncertainty = 1.96 * ((posterior * (1.0 - posterior) / (prior_strength + len(peers))) ** 0.5)
        cap = (
            0.88 if len(peers) >= 500 and uncertainty <= 0.04
            else 0.84 if len(peers) >= 300 and uncertainty <= 0.06
            else 0.80 if len(peers) >= 200 and uncertainty <= 0.08
            else 0.76 if len(peers) >= 100
            else 0.72
        )
        calibrated = max(0.02, min(cap, posterior))
        return {
            "probability": round(calibrated * 100.0, 2),
            "raw_probability": round(raw * 100.0, 2),
            "tier": tier,
            "sample_size": len(peers),
            "uncertainty_points": round(uncertainty * 100.0, 2),
            "paid_eligible": segment_samples >= 100 and len(peers) >= 50 and uncertainty <= 0.10,
            "segment_sample_size": segment_samples,
            "segment_maturity": maturity,
            "segment_next_threshold": 100 if segment_samples < 100 else 200 if segment_samples < 200 else 500,
            "confidence_cap": round(cap * 100.0, 1),
            "cap_reason": "Confidence is capped until this segment has enough precise independent outcomes.",
        }

    cap = 0.65
    return {
        "probability": round(min(raw, cap) * 100.0, 2),
        "raw_probability": round(raw * 100.0, 2),
        "tier": "uncalibrated",
        "sample_size": 0,
        "uncertainty_points": 50.0,
        "paid_eligible": False,
        "segment_sample_size": segment_samples,
        "segment_maturity": maturity,
        "segment_next_threshold": 100 if segment_samples < 100 else 200 if segment_samples < 200 else 500,
        "confidence_cap": cap * 100.0,
        "cap_reason": "Uncalibrated predictions cannot exceed 65% confidence.",
    }


def _matches(row: dict, target: dict, fields: tuple[str, ...]) -> bool:
    for field in fields:
        observed = str(row.get(field) or "").strip().lower()
        if observed != target[field]:
            return False
    return True
