from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.entity_normalization import canonical_person_key
from utils.stat_normalization import canonical_stat_label


MODEL_VERSION = "edgeiq-historical-distribution-v2.0"
MIN_HISTORY_FOR_FORECAST = 5
MIN_HISTORY_FOR_PAID = 20


@dataclass(frozen=True)
class PropForecast:
    projection: float
    probability: float
    standard_deviation: float
    sample_size: int
    effective_sample_size: float
    source: str
    model_version: str
    paid_eligible: bool
    reason: str
    feature_as_of: str
    features: dict

    def snapshot(self) -> dict:
        return asdict(self)


def forecast_prop(
    player: str,
    sport: str,
    stat: str,
    line: float,
    direction: str = "Over",
    *,
    history: list[dict] | None = None,
    game_time: object = None,
    team: str = "",
    game: str = "",
) -> PropForecast:
    rows = list(history) if history is not None else FinalStatsRepository.history(player, stat, sport=sport, limit=100)
    rows = _eligible_history(rows, game_time)
    actuals = [float(row["actual"]) for row in rows]
    feature_as_of = datetime.now(timezone.utc).isoformat()

    if len(actuals) < MIN_HISTORY_FOR_FORECAST:
        return PropForecast(
            projection=round(float(line), 2),
            probability=50.0,
            standard_deviation=0.0,
            sample_size=len(actuals),
            effective_sample_size=float(len(actuals)),
            source="market_prior",
            model_version=MODEL_VERSION,
            paid_eligible=False,
            reason=f"Only {len(actuals)} verified games; at least {MIN_HISTORY_FOR_FORECAST} are required for a forecast.",
            feature_as_of=feature_as_of,
            features={
                "player_key": canonical_person_key(player),
                "sport": sport.upper(),
                "stat": canonical_stat_label(stat),
                "verified_games": len(actuals),
                "market_line_used_as_prior": True,
            },
        )

    weights = [_recency_weight(index) for index in range(len(actuals))]
    weight_sum = sum(weights)
    weighted_mean = sum(value * weight for value, weight in zip(actuals, weights, strict=False)) / weight_sum
    side = _game_side(game, team)
    side_values = [
        float(row["actual"]) for row in rows
        if side and _game_side(str(row.get("game") or ""), str(row.get("team") or team)) == side
    ]
    opponent = _opponent(game, team)
    opponent_values = [
        float(row["actual"]) for row in rows
        if opponent and opponent == _opponent(str(row.get("game") or ""), str(row.get("team") or team))
    ]
    contextual_mean = weighted_mean
    if len(side_values) >= 5:
        contextual_mean = contextual_mean * 0.80 + (sum(side_values) / len(side_values)) * 0.20
    if len(opponent_values) >= 3:
        contextual_mean = contextual_mean * 0.85 + (sum(opponent_values) / len(opponent_values)) * 0.15
    variance = sum(
        weight * ((value - contextual_mean) ** 2)
        for value, weight in zip(actuals, weights, strict=False)
    ) / weight_sum
    sigma = max(_minimum_sigma(stat, weighted_mean), math.sqrt(max(variance, 0.0)))
    effective_n = (weight_sum * weight_sum) / sum(weight * weight for weight in weights)
    probability = _side_probability(contextual_mean, sigma, float(line), direction, stat)
    paid_eligible = len(actuals) >= MIN_HISTORY_FOR_PAID and effective_n >= 8
    recent = actuals[:5]

    return PropForecast(
        projection=round(contextual_mean, 2),
        probability=round(probability * 100.0, 2),
        standard_deviation=round(sigma, 3),
        sample_size=len(actuals),
        effective_sample_size=round(effective_n, 2),
        source="verified_history_distribution",
        model_version=MODEL_VERSION,
        paid_eligible=paid_eligible,
        reason=(
            "Verified history clears the minimum paid-model evidence threshold."
            if paid_eligible
            else f"Forecast available, but paid mode requires {MIN_HISTORY_FOR_PAID} verified games."
        ),
        feature_as_of=feature_as_of,
        features={
            "player_key": canonical_person_key(player),
            "sport": sport.upper(),
            "stat": canonical_stat_label(stat),
            "verified_games": len(actuals),
            "effective_sample_size": round(effective_n, 2),
            "weighted_mean": round(weighted_mean, 3),
            "contextual_mean": round(contextual_mean, 3),
            "recent_5_mean": round(sum(recent) / len(recent), 3),
            "standard_deviation": round(sigma, 3),
            "recency_decay": 0.93,
            "market_line_used_as_prior": False,
            "home_away": side or "unknown",
            "home_away_sample": len(side_values),
            "opponent": opponent,
            "opponent_sample": len(opponent_values),
            "rest_days": _rest_days(game_time, rows),
            "missingness": {
                "home_away": not bool(side),
                "opponent": not bool(opponent),
                "rest_days": _rest_days(game_time, rows) is None,
            },
        },
    )


def _eligible_history(rows: list[dict], game_time: object) -> list[dict]:
    cutoff = _date_text(game_time)
    eligible = [
        row
        for row in rows
        if str(row.get("status") or "played").lower() == "played"
        and row.get("actual") is not None
        and (not cutoff or not row.get("game_date") or str(row["game_date"]) < cutoff)
    ]
    eligible.sort(key=lambda row: (str(row.get("game_date") or ""), str(row.get("game") or "")), reverse=True)
    return eligible


def _side_probability(mean: float, sigma: float, line: float, direction: str, stat: str) -> float:
    discrete = _is_discrete_stat(stat)
    threshold = line + (0.5 if discrete and float(line).is_integer() else 0.0)
    over_probability = 1.0 - _normal_cdf((threshold - mean) / sigma)
    selected = 1.0 - over_probability if str(direction).lower() == "under" else over_probability
    return max(0.02, min(0.98, selected))


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _recency_weight(index: int) -> float:
    return 0.93 ** index


def _minimum_sigma(stat: str, mean: float) -> float:
    key = canonical_stat_label(stat).lower()
    if any(token in key for token in ("home run", "goal", "steal", "block", "rbi", "run", "hit")):
        return 0.75
    if any(token in key for token in ("assist", "rebound", "strikeout", "save")):
        return max(1.25, abs(mean) * 0.18)
    return max(1.75, abs(mean) * 0.16)


def _is_discrete_stat(stat: str) -> bool:
    key = canonical_stat_label(stat).lower()
    return not any(token in key for token in ("yards", "fantasy", "percentage"))


def _date_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else ""


def _game_side(game: str, team: str) -> str:
    compact = str(game or "").upper().replace(" ", "")
    team_key = str(team or "").upper().replace(" ", "")
    if "@" not in compact or not team_key:
        return ""
    away, home = compact.split("@", 1)
    if team_key == away:
        return "away"
    if team_key == home:
        return "home"
    return ""


def _opponent(game: str, team: str) -> str:
    compact = str(game or "").upper().replace(" ", "")
    team_key = str(team or "").upper().replace(" ", "")
    if "@" not in compact or not team_key:
        return ""
    away, home = compact.split("@", 1)
    if team_key == away:
        return home
    if team_key == home:
        return away
    return ""


def _rest_days(game_time: object, rows: list[dict]) -> int | None:
    target = _date_text(game_time)
    historical = [str(row.get("game_date") or "")[:10] for row in rows if row.get("game_date")]
    if not target or not historical:
        return None
    try:
        target_date = datetime.fromisoformat(target).date()
        latest = max(datetime.fromisoformat(value).date() for value in historical)
    except ValueError:
        return None
    return max(0, (target_date - latest).days)
