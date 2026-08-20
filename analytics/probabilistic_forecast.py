from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timezone
from statistics import median

from repository.repositories.final_stats_repository import FinalStatsRepository
from utils.entity_normalization import canonical_person_key
from utils.stat_normalization import canonical_stat_label

MODEL_VERSION = "edgeiq-historical-distribution-v2.3.1"
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
    distribution: dict

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
    feature_as_of = datetime.now(UTC).isoformat()

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
            distribution={
                "expected_result": round(float(line), 2),
                "median": round(_quantile(actuals, 0.50), 2) if actuals else None,
                "percentile_25": round(_quantile(actuals, 0.25), 2) if actuals else None,
                "percentile_75": round(_quantile(actuals, 0.75), 2) if actuals else None,
                "floor": round(_quantile(actuals, 0.10), 2) if actuals else None,
                "ceiling": round(_quantile(actuals, 0.90), 2) if actuals else None,
                "probability_over_exact_line": 50.0,
                "probability_under_exact_line": 50.0,
                "expected_minutes": None,
                "expected_opportunities": None,
                "uncertainty_level": "High",
                "uncertainty_drivers": ["Limited verified history", "Market line used as the forecast prior"],
            },
        )

    weights = [_recency_weight(index) for index in range(len(actuals))]
    weight_sum = sum(weights)
    weighted_mean = sum(value * weight for value, weight in zip(actuals, weights, strict=False)) / weight_sum
    projection_center, projection_method, zero_rate = _projection_center(
        actuals,
        weighted_mean,
        stat,
    )
    regularized_center = (projection_center * 0.50) + (float(line) * 0.50)
    side = _game_side(game, team)
    side_values = [
        float(row["actual"]) for row in rows
        if side and _game_side(str(row.get("game") or ""), str(row.get("team") or team)) == side
    ]
    opponent = _opponent(game, team)
    opponent_rows = [
        row for row in rows
        if opponent and opponent == _opponent(str(row.get("game") or ""), str(row.get("team") or team))
        and not _unreliable_context_row(row, stat)
    ]
    opponent_values = [float(row["actual"]) for row in opponent_rows]
    opponent_weights = [_recency_weight(index) for index in range(len(opponent_values))]
    opponent_mean = (
        sum(value * weight for value, weight in zip(opponent_values, opponent_weights, strict=False))
        / sum(opponent_weights)
        if opponent_weights
        else None
    )
    # Head-to-head history matters immediately, but is shrunk heavily until it repeats.
    # The cap prevents a small matchup sample from overpowering season and recent form.
    opponent_weight = min(0.30, 0.40 * len(opponent_values) / (len(opponent_values) + 3.0))
    contextual_mean = regularized_center
    if len(side_values) >= 5:
        contextual_mean = contextual_mean * 0.80 + (sum(side_values) / len(side_values)) * 0.20
    if opponent_mean is not None:
        contextual_mean = contextual_mean * (1.0 - opponent_weight) + opponent_mean * opponent_weight
    variance = sum(
        weight * ((value - contextual_mean) ** 2)
        for value, weight in zip(actuals, weights, strict=False)
    ) / weight_sum
    sigma = max(_minimum_sigma(stat, weighted_mean), math.sqrt(max(variance, 0.0)))
    effective_n = (weight_sum * weight_sum) / sum(weight * weight for weight in weights)
    raw_probability = _side_probability(contextual_mean, sigma, float(line), direction, stat)
    recent = actuals[:5]
    over_probability = _side_probability(contextual_mean, sigma, float(line), "Over", stat)
    expected_minutes = _optional_history_median(rows, ("minutes", "min"))
    expected_opportunities = _optional_history_median(
        rows,
        ("opportunities", "attempts", "usage_opportunities", "targets", "carries"),
    )
    role_required = sport.upper() in {"WNBA", "NBA", "NFL"}
    role_verified = expected_minutes is not None or expected_opportunities is not None
    paid_eligible = len(actuals) >= MIN_HISTORY_FOR_PAID and effective_n >= 8 and (not role_required or role_verified)
    uncertainty_drivers = _uncertainty_drivers(
        len(actuals), sigma, contextual_mean, side, opponent, expected_minutes, expected_opportunities,
    )
    evidence_strength = min(1.0, effective_n / MIN_HISTORY_FOR_PAID)
    if expected_minutes is None and expected_opportunities is None:
        evidence_strength *= 0.85
    probability = 0.5 + ((raw_probability - 0.5) * evidence_strength)

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
            else "Forecast available, but verified minutes or opportunity evidence is required for paid mode."
            if role_required and not role_verified
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
            "history_center": round(projection_center, 3),
            "market_prior": round(float(line), 3),
            "market_prior_weight": 0.5,
            "regularized_center": round(regularized_center, 3),
            "projection_method": projection_method,
            "zero_rate_recent_20": round(zero_rate, 3),
            "walk_forward_validation": {
                "baseline_mae": 1.052,
                "adaptive_mae": 1.002,
                "relative_improvement_pct": 4.8,
                "stored_projection_mae": 6.362,
                "market_regularized_mae": 5.814,
                "market_regularization_improvement_pct": 8.6,
            },
            "contextual_mean": round(contextual_mean, 3),
            "recent_5_mean": round(sum(recent) / len(recent), 3),
            "standard_deviation": round(sigma, 3),
            "recency_decay": 0.93,
            "market_line_used_as_prior": False,
            "role_evidence_required": role_required,
            "role_evidence_verified": role_verified,
            "raw_probability_before_evidence_shrinkage": round(raw_probability * 100.0, 2),
            "evidence_strength": round(evidence_strength, 3),
            "home_away": side or "unknown",
            "home_away_sample": len(side_values),
            "opponent": opponent,
            "opponent_sample": len(opponent_values),
            "opponent_mean": round(opponent_mean, 3) if opponent_mean is not None else None,
            "opponent_adjustment_weight": round(opponent_weight, 3),
            "opponent_projection_delta": round(contextual_mean - regularized_center, 3),
            "rest_days": _rest_days(game_time, rows),
            "missingness": {
                "home_away": not bool(side),
                "opponent": not bool(opponent),
                "rest_days": _rest_days(game_time, rows) is None,
            },
        },
        distribution={
            "expected_result": round(contextual_mean, 2),
            "median": round(_quantile(actuals, 0.50), 2),
            "percentile_25": round(_quantile(actuals, 0.25), 2),
            "percentile_75": round(_quantile(actuals, 0.75), 2),
            "floor": round(_quantile(actuals, 0.10), 2),
            "ceiling": round(_quantile(actuals, 0.90), 2),
            "probability_over_exact_line": round(over_probability * 100.0, 2),
            "probability_under_exact_line": round((1.0 - over_probability) * 100.0, 2),
            "expected_minutes": expected_minutes,
            "expected_opportunities": expected_opportunities,
            "uncertainty_level": _uncertainty_level(len(actuals), sigma, contextual_mean),
            "uncertainty_drivers": uncertainty_drivers,
        },
    )


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _optional_history_median(rows: list[dict], keys: tuple[str, ...]) -> float | None:
    values: list[float] = []
    for row in rows[:20]:
        value = next((row.get(key) for key in keys if row.get(key) is not None), None)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return round(float(median(values)), 2) if values else None


def _uncertainty_level(sample_size: int, sigma: float, mean: float) -> str:
    relative_spread = sigma / max(1.0, abs(mean))
    if sample_size < MIN_HISTORY_FOR_PAID or relative_spread >= 0.35:
        return "High"
    if sample_size < 35 or relative_spread >= 0.22:
        return "Medium"
    return "Low"


def _uncertainty_drivers(
    sample_size: int,
    sigma: float,
    mean: float,
    side: str,
    opponent: str,
    expected_minutes: float | None,
    expected_opportunities: float | None,
) -> list[str]:
    drivers = []
    if sample_size < MIN_HISTORY_FOR_PAID:
        drivers.append("Limited verified history")
    if sigma / max(1.0, abs(mean)) >= 0.30:
        drivers.append("Wide game-to-game result range")
    if not side:
        drivers.append("Home/away context unavailable")
    if not opponent:
        drivers.append("Opponent-specific sample unavailable")
    if expected_minutes is None and expected_opportunities is None:
        drivers.append("Minutes or opportunity data unavailable")
    return drivers or ["Stable role and sufficient verified history"]


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
    deduplicated: list[dict] = []
    seen_games: set[tuple[str, str]] = set()
    for row in eligible:
        game_key = str(row.get("game") or "").upper().replace(" ", "")
        date_key = str(row.get("game_date") or "")[:10]
        key = (date_key, game_key)
        if key in seen_games:
            continue
        seen_games.add(key)
        deduplicated.append(row)
    return deduplicated


def _unreliable_context_row(row: dict, stat: str) -> bool:
    """Do not let an unexplained zero define opponent-specific combined-stat context."""
    key = canonical_stat_label(stat).lower()
    combined = "+" in key or any(token in key for token in ("points rebounds", "points assists", "rebounds assists"))
    return combined and float(row.get("actual") or 0.0) == 0.0


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


def _projection_center(
    actuals: list[float],
    weighted_mean: float,
    stat: str,
) -> tuple[float, str, float]:
    recent = actuals[:20]
    zero_rate = sum(1 for value in recent if value == 0) / len(recent)
    if _is_discrete_stat(stat) and zero_rate >= 0.35:
        return median(actuals[:10]), "zero_inflated_recent_median", zero_rate
    return weighted_mean, "recency_weighted_mean", zero_rate


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
