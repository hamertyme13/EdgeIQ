from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class OpportunityAdjustment:
    metric: str
    factor: float
    absolute_delta: float
    reason: str
    source_feature: str
    existing_equivalent: str
    treatment: str

    def snapshot(self) -> dict:
        return asdict(self)


def prop_opportunity_context(
    sport: str,
    stat: str,
    team: str,
    game_prediction: dict,
    *,
    expected_minutes: float | None = None,
    expected_opportunities: float | None = None,
) -> dict:
    """Build a shadow opportunity adjustment; never modify confidence directly."""
    sport_key = str(sport or "").upper()
    stat_key = str(stat or "").lower()
    is_home = str(team or "").strip().lower() == str(game_prediction.get("home_team") or "").strip().lower()
    team_margin = float(game_prediction.get("expected_margin") or 0.0) * (1.0 if is_home else -1.0)
    blowout = float(game_prediction.get("blowout_probability") or 0.0)
    pace = game_prediction.get("expected_pace")
    adjustments: list[OpportunityAdjustment] = []

    if sport_key in {"NBA", "WNBA"}:
        if expected_minutes is not None and blowout >= 0.35:
            delta = -min(2.5, expected_minutes * blowout * 0.08)
            adjustments.append(OpportunityAdjustment(
                "minutes", 1.0 + delta / expected_minutes, delta,
                "Elevated blowout risk may reduce late-game rotation minutes.",
                "blowout_probability", "minutes/workload history", "residual",
            ))
        if expected_opportunities is not None and pace is not None:
            league_pace = 100.0 if sport_key == "NBA" else 80.0
            factor = max(0.96, min(1.04, float(pace) / league_pace))
            adjustments.append(OpportunityAdjustment(
                "possessions", factor, expected_opportunities * (factor - 1.0),
                "Projected pace changes possession opportunity.",
                "expected_pace", "recent opportunity rate", "residual",
            ))
    elif sport_key in {"NFL", "NCAAF"} and expected_opportunities is not None:
        receiving = any(token in stat_key for token in ("receiv", "target", "reception", "pass"))
        rushing = any(token in stat_key for token in ("rush", "carr"))
        if receiving and team_margin <= -3:
            factor = 1.0 + min(0.08, abs(team_margin) / 200.0)
            adjustments.append(OpportunityAdjustment("attempts_or_targets", factor, expected_opportunities * (factor - 1), "Projected trailing script can increase passing volume.", "expected_margin", "historical attempts/targets", "residual"))
        elif rushing and team_margin >= 3:
            factor = 1.0 + min(0.07, team_margin / 220.0)
            adjustments.append(OpportunityAdjustment("carries", factor, expected_opportunities * (factor - 1), "Projected leading script can increase rushing volume.", "expected_margin", "historical carries", "residual"))
    elif sport_key == "MLB" and expected_opportunities is not None:
        factor = max(0.97, min(1.03, float(game_prediction.get("expected_total") or 8.5) / 8.5))
        adjustments.append(OpportunityAdjustment("plate_appearances", factor, expected_opportunities * (factor - 1), "Expected run environment changes plate-appearance and scoring opportunity slightly.", "expected_total", "market line and recent batting opportunity", "residual"))
    elif sport_key == "NHL" and expected_opportunities is not None:
        factor = max(0.97, min(1.03, float(game_prediction.get("expected_total") or 6.0) / 6.0))
        adjustments.append(OpportunityAdjustment("shots_or_scoring_chances", factor, expected_opportunities * (factor - 1), "Expected scoring environment changes shot and point opportunity slightly.", "expected_total", "recent shot opportunity", "residual"))

    combined_factor = 1.0
    for adjustment in adjustments:
        combined_factor *= adjustment.factor
    return {
        "model_version": "edgeiq-game-context-prop-distribution-v2.5.0",
        "shadow_only": True,
        "confidence_delta": 0.0,
        "team_win_probability": game_prediction.get("home_win_probability") if is_home else game_prediction.get("away_win_probability"),
        "opponent_win_probability": game_prediction.get("away_win_probability") if is_home else game_prediction.get("home_win_probability"),
        "expected_margin": round(team_margin, 2),
        "expected_total": game_prediction.get("expected_total"),
        "expected_team_points": game_prediction.get("expected_home_points") if is_home else game_prediction.get("expected_away_points"),
        "pace_factor": next((row.factor for row in adjustments if row.metric == "possessions"), 1.0),
        "blowout_probability": blowout,
        "game_script": game_prediction.get("game_script", "neutral"),
        "game_script_confidence": game_prediction.get("game_script_confidence", 0.0),
        "opportunity_factor": round(combined_factor, 4),
        "adjustments": [row.snapshot() for row in adjustments],
        "anti_double_counting": "Residual opportunity adjustments only; market prior, opponent history, injuries, and role evidence are not re-added.",
    }
