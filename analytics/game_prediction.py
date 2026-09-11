from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from analytics.game_model_registry import GAME_MARKET_CHAMPION_VERSION


@dataclass(frozen=True)
class GamePrediction:
    sport: str
    game_id: str
    game: str
    home_team: str
    away_team: str
    home_win_probability: float
    away_win_probability: float
    expected_margin: float
    expected_total: float
    expected_home_points: float
    expected_away_points: float
    expected_pace: float | None = None
    blowout_probability: float | None = None
    game_script: str = "neutral"
    game_script_confidence: float = 0.0
    model_version: str = GAME_MARKET_CHAMPION_VERSION
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    game_start: str = ""
    data_quality: str = "Thin"
    evidence: dict = field(default_factory=dict)

    def snapshot(self) -> dict:
        return asdict(self)


def predict_game(features: dict, *, model_version: str = GAME_MARKET_CHAMPION_VERSION) -> GamePrediction:
    market_home = _probability(features.get("market_home_probability"), 0.5)
    historical_home = _probability(features.get("historical_home_probability"), market_home)
    quality_score = max(0.0, min(100.0, float(features.get("data_quality_score") or 0.0)))
    historical_weight = min(0.25, float(features.get("historical_sample_size") or 0.0) / 200.0)
    if model_version == GAME_MARKET_CHAMPION_VERSION:
        home_probability = market_home
        method = "no_vig_market_baseline"
    else:
        home_probability = market_home * (1.0 - historical_weight) + historical_home * historical_weight
        method = "market_plus_shrunk_historical_residual"
    home_probability = max(0.05, min(0.95, home_probability))
    away_probability = 1.0 - home_probability

    market_total = float(features.get("market_total") or _default_total(features.get("sport")))
    market_margin = features.get("market_home_margin")
    expected_margin = float(market_margin) if market_margin is not None else _probability_margin(home_probability)
    residual_margin = float(features.get("historical_margin_residual") or 0.0)
    if model_version != GAME_MARKET_CHAMPION_VERSION:
        expected_margin += max(-3.0, min(3.0, residual_margin * historical_weight))
    expected_home = (market_total + expected_margin) / 2.0
    expected_away = market_total - expected_home
    blowout_threshold = 10.0 if str(features.get("sport") or "").upper() in {"NBA", "WNBA"} else 14.0
    blowout_probability = max(0.05, min(0.85, abs(expected_margin) / (blowout_threshold * 1.8)))
    script = "home_leading" if expected_margin >= 3 else "away_leading" if expected_margin <= -3 else "neutral"
    script_confidence = min(1.0, abs(expected_margin) / max(1.0, blowout_threshold))
    return GamePrediction(
        sport=str(features.get("sport") or "").upper(),
        game_id=str(features.get("game_id") or ""),
        game=str(features.get("game") or ""),
        home_team=str(features.get("home_team") or ""),
        away_team=str(features.get("away_team") or ""),
        home_win_probability=round(home_probability, 4),
        away_win_probability=round(away_probability, 4),
        expected_margin=round(expected_margin, 2),
        expected_total=round(market_total, 2),
        expected_home_points=round(expected_home, 2),
        expected_away_points=round(expected_away, 2),
        expected_pace=_optional_float(features.get("expected_pace")),
        blowout_probability=round(blowout_probability, 4),
        game_script=script,
        game_script_confidence=round(script_confidence, 3),
        model_version=model_version,
        game_start=str(features.get("game_start") or ""),
        data_quality=_quality_label(quality_score),
        evidence={**features, "prediction_method": method, "historical_weight": round(historical_weight, 3)},
    )


def _probability(value: object, default: float) -> float:
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return default
    if probability > 1.0:
        probability /= 100.0
    return max(0.0, min(1.0, probability))


def _probability_margin(probability: float) -> float:
    return max(-18.0, min(18.0, math.log(probability / (1.0 - probability)) * 4.5))


def _default_total(sport: object) -> float:
    return {"NBA": 222.0, "WNBA": 162.0, "NFL": 44.0, "NCAAF": 51.0, "MLB": 8.5, "NHL": 6.0}.get(
        str(sport or "").upper(), 1.0,
    )


def _optional_float(value: object) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _quality_label(score: float) -> str:
    return "Strong" if score >= 75 else "Moderate" if score >= 50 else "Thin"
