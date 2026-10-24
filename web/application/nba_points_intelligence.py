"""Verified, descriptive NBA points research; never a paid recommendation source."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from math import isfinite, sqrt
from statistics import mean, median, pstdev

from analytics.probabilistic_forecast import PropForecast, forecast_probability_at_line
from services.game_team_features import opponent_points_allowed_context
from utils.entity_normalization import canonical_matchup_key

THRESHOLDS = (10, 15, 20, 25, 30, 35)
VERIFIED_SOURCES = ("espn", "nba_api", "balldontlie", "statshawk")
NON_REGULAR_SEASONS = {"preseason", "postseason", "playoffs", "summer_league", "summer league", "exhibition"}


def _opponent(game: object, team: object) -> str:
    matchup = str(game or "").replace(" ", "").upper()
    team_key = str(team or "").replace(" ", "").upper()
    if "@" not in matchup or not team_key:
        return ""
    away, home = matchup.split("@", 1)
    return home if away == team_key else away if home == team_key else ""


def _screen_games(history: list[dict], game_time: object) -> tuple[list[dict], dict]:
    try:
        target = datetime.fromisoformat(str(game_time).replace("Z", "+00:00")).date() if game_time else datetime.now(UTC).date()
    except ValueError:
        target = datetime.now(UTC).date()
    season_year = target.year if target.month >= 9 else target.year - 1
    season_start = f"{season_year}-09-15"
    excluded: Counter[str] = Counter()
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in history:
        day = str(row.get("game_date") or "")[:10]
        if not day or not season_start <= day < target.isoformat():
            excluded["outside_pregame_season"] += 1
            continue
        if str(row.get("status") or "played").lower() != "played":
            excluded["not_played"] += 1
            continue
        if not str(row.get("source") or "").lower().startswith(VERIFIED_SOURCES):
            excluded["unverified_source"] += 1
            continue
        try:
            points = float(row["actual"])
        except (KeyError, TypeError, ValueError):
            excluded["invalid_points"] += 1
            continue
        if not isfinite(points) or not 0 <= points <= 100:
            excluded["implausible_points"] += 1
            continue
        game_key = canonical_matchup_key(row.get("game"), {"SAS": "SA", "GSW": "GS", "NYK": "NY"})
        if "@" not in game_key:
            excluded["missing_matchup"] += 1
            continue
        grouped[(day, game_key)].append({**row, "actual": points})
    games = []
    for _key, rows in grouped.items():
        season_labels = {str(row.get("season_type") or "").lower() for row in rows}
        if season_labels.issubset(NON_REGULAR_SEASONS):
            excluded["other_season"] += len(rows)
            continue
        if season_labels.intersection(NON_REGULAR_SEASONS):
            excluded["conflicting_season_type"] += len(rows)
            continue
        if len({row["actual"] for row in rows}) != 1:
            excluded["conflicting_final"] += len(rows)
            continue
        excluded["matching_duplicate"] += len(rows) - 1
        # Prefer explicit regular-season provenance over an otherwise identical unlabeled final.
        games.append(max(rows, key=lambda row: (str(row.get("season_type") or "").lower() == "regular", str(row.get("imported_at") or ""))))
    games.sort(key=lambda row: (str(row.get("game_date") or ""), canonical_matchup_key(row.get("game"))), reverse=True)
    imported = [str(row.get("imported_at")) for row in games if row.get("imported_at")]
    return games, {
        "screened_rows": len(history),
        "accepted_games": len(games),
        "excluded": dict(sorted(excluded.items())),
        "latest_stored_final_at": max(imported, default=None),
        "accepted_sources": dict(sorted(Counter(str(row.get("source") or "") for row in games).items())),
    }


def _eligible_games(history: list[dict], game_time: object) -> list[dict]:
    return _screen_games(history, game_time)[0]


def _interval(wins: int, decisions: int) -> list[float] | None:
    if not decisions:
        return None
    # Wilson 95% interval describes uncertainty in the historical rate, not
    # uncertainty in EdgeIQ's next-game probability.
    z = 1.96
    p = wins / decisions
    denominator = 1 + z * z / decisions
    center = (p + z * z / (2 * decisions)) / denominator
    margin = z * sqrt(p * (1 - p) / decisions + z * z / (4 * decisions * decisions)) / denominator
    return [round(max(0.0, center - margin) * 100, 1), round(min(1.0, center + margin) * 100, 1)]


def _summary(rows: list[dict], threshold: float, *, inclusive: bool) -> dict:
    values = [row["actual"] for row in rows]
    wins = sum(value >= threshold if inclusive else value > threshold for value in values)
    pushes = 0 if inclusive else sum(value == threshold for value in values)
    decisions = len(values) - pushes
    return {
        "hits": wins,
        "games": len(values),
        "pushes": pushes,
        "decisions": decisions,
        "hit_rate": round(100 * wins / decisions, 1) if decisions else None,
        "interval_95": _interval(wins, decisions),
        "average": round(mean(values), 2) if values else None,
        "median": round(median(values), 2) if values else None,
        "standard_deviation": round(pstdev(values), 2) if len(values) > 1 else None,
    }


def _chronological_baselines(games: list[dict]) -> dict:
    actuals = [row["actual"] for row in reversed(games)]
    if len(actuals) < 6:
        return {"evaluated_games": 0, "status": "At least six verified games are needed for a chronological baseline."}
    errors: dict[str, list[float]] = {"prior_5_average": [], "prior_season_average": []}
    for index in range(5, len(actuals)):
        actual = actuals[index]
        errors["prior_5_average"].append(mean(actuals[index - 5:index]) - actual)
        errors["prior_season_average"].append(mean(actuals[:index]) - actual)
    return {
        "evaluated_games": len(errors["prior_5_average"]),
        "status": "Descriptive rolling baselines; no sportsbook price or champion comparison.",
        "baselines": {
            name: {
                "mae": round(mean(abs(error) for error in values), 2),
                "rmse": round(sqrt(mean(error * error for error in values)), 2),
            }
            for name, values in errors.items()
        },
        "brier_score": None,
        "note": "Every test game uses only earlier finals. Baseline errors do not validate an exact-line probability.",
    }


def _minutes_challenger(games: list[dict]) -> dict:
    rows = []
    for row in games:
        if str(row.get("season_type") or "").lower() != "regular":
            continue
        try:
            minutes = float(row["verified_minutes"])
        except (KeyError, TypeError, ValueError):
            continue
        if isfinite(minutes) and 0 < minutes <= 65:
            rows.append((row["actual"], minutes))
    result = {
        "status": "insufficient_verified_minutes",
        "sample_size": len(rows),
        "expected_points": None,
        "expected_minutes": None,
        "points_per_minute": None,
        "probability": None,
        "validation": {"evaluated_games": 0, "challenger": None, "recent_points_average": None},
        "note": "Research-only minutes baseline; no calibrated probability or recommendation override.",
    }
    if len(rows) < 5:
        return result

    def predict(prior: list[tuple[float, float]]) -> float:
        recent = prior[-10:]
        return median(minutes for _, minutes in prior[-5:]) * sum(points for points, _ in recent) / sum(
            minutes for _, minutes in recent
        )

    chronological = list(reversed(rows))
    challenger_errors = []
    recent_errors = []
    for index in range(5, len(chronological)):
        prior = chronological[:index]
        actual = chronological[index][0]
        challenger_errors.append(predict(prior) - actual)
        recent_errors.append(mean(points for points, _ in prior[-5:]) - actual)

    def metrics(errors: list[float]) -> dict | None:
        if not errors:
            return None
        return {
            "mae": round(mean(abs(error) for error in errors), 2),
            "rmse": round(sqrt(mean(error * error for error in errors)), 2),
        }

    recent = rows[:10]
    result.update({
        "status": "shadow_evaluation" if challenger_errors else "awaiting_holdout",
        "expected_points": round(predict(chronological), 2),
        "expected_minutes": round(median(minutes for _, minutes in rows[:5]), 1),
        "points_per_minute": round(sum(points for points, _ in recent) / sum(minutes for _, minutes in recent), 3),
        "validation": {
            "evaluated_games": len(challenger_errors),
            "challenger": metrics(challenger_errors),
            "recent_points_average": metrics(recent_errors),
        },
    })
    return result


def build_nba_points_intelligence(
    history: list[dict],
    *,
    line: float | None,
    forecast: PropForecast | None,
    opponent: str,
    game_time: object = None,
    team_games: list[dict] | None = None,
) -> dict:
    games, reliability = _screen_games(history, game_time)
    regular_games = sum(str(row.get("season_type") or "").lower() == "regular" for row in games)
    unverified_games = len(games) - regular_games
    windows = {
        "last_5": games[:5],
        "last_10": games[:10],
        "last_20": games[:20],
        "season": games,
        "verified_season": [row for row in games if str(row.get("season_type") or "").lower() == "regular"],
        "home": [row for row in games if _opponent(row.get("game"), row.get("team"))
                 and str(row.get("game") or "").replace(" ", "").upper().endswith("@" + str(row.get("team") or "").upper())],
        "away": [row for row in games if _opponent(row.get("game"), row.get("team"))
                 and str(row.get("game") or "").replace(" ", "").upper().startswith(str(row.get("team") or "").upper() + "@")],
        "opponent": [row for row in games if opponent and _opponent(row.get("game"), row.get("team")) == opponent],
    }
    thresholds = {
        name: {
            "games": len(rows),
            "thresholds": [{"points": threshold, **_summary(rows, threshold, inclusive=True)} for threshold in THRESHOLDS],
            "custom_line": _summary(rows, float(line), inclusive=False) if line is not None else None,
        }
        for name, rows in windows.items()
    }
    values = [row["actual"] for row in games[:20]]
    variability = round(pstdev(values) / mean(values), 3) if len(values) > 1 and mean(values) > 0 else None
    conflicting_evidence = any(
        reliability["excluded"].get(reason, 0)
        for reason in ("conflicting_final", "conflicting_season_type")
    )
    verified_model = bool(
        forecast and forecast.source == "verified_history_distribution" and not conflicting_evidence
    )
    over = forecast_probability_at_line(forecast, float(line), "Over", "Points") if verified_model and line is not None else None
    under = forecast_probability_at_line(forecast, float(line), "Under", "Points") if verified_model and line is not None else None
    head_to_head = thresholds["opponent"]["custom_line"] if line is not None else None
    team_defense = opponent_points_allowed_context(opponent, str(game_time or ""), team_games or [])
    return {
        "status": "research_only",
        "sample_size": len(games),
        "data_reliability": reliability,
        "season_provenance": {
            "regular_games": regular_games,
            "unverified_games": unverified_games,
            "status": "verified_regular" if not unverified_games else "season_type_unverified",
        },
        "data_quality": (
            "Season unverified" if unverified_games else
            "Developing" if len(games) >= 10 else "Thin history" if games else "Unavailable"
        ),
        "thresholds": thresholds,
        "consistency": {
            "coefficient_of_variation": variability,
            "description": "Last 20 points standard deviation divided by average; lower means less variation. Not a hit probability.",
        },
        "validation": _chronological_baselines(games),
        "minutes_challenger": _minutes_challenger(games),
        "matchup": {
            "opponent": opponent or None,
            "head_to_head_games": len(windows["opponent"]),
            "head_to_head_over_rate": head_to_head["hit_rate"] if head_to_head else None,
            "advantage_score": None,
            "defensive_rank": None,
            "team_points_allowed": team_defense,
            "status": (
                "Verified team points allowed available; position-specific defense and matchup score are unvalidated."
                if team_defense["sample_size"] else
                "Opponent defensive evidence unavailable; head-to-head is descriptive only."
            ),
        },
        "projection": {
            "expected_points": forecast.projection if verified_model else None,
            "over_probability": over,
            "under_probability": under,
            "source": forecast.source if forecast else "unavailable",
            "model_version": forecast.model_version if forecast else None,
            "note": (
                "Research forecast withheld because stored finals disagree. The production forecast is unchanged."
                if conflicting_evidence else
                "Existing EdgeIQ forecast shown separately from historical hit rates. No model override or verified EV claim."
            ),
        },
        "market": {"status": "No Validated Edge", "ev": None, "reason": "Exact over/under prices and validated model edge are required."},
        "explanation": (
            f"{len(games)} verified games in the tracked NBA season window are available. "
            + (f"Against {opponent}, {len(windows['opponent'])} historical games are available. " if opponent else "")
            + "Historical hit rates describe past results; the forecast is a separate estimate. "
            + (f"{unverified_games} historical games lack confirmed season type; those tracked-window rates are not regular-season-only. " if unverified_games else "All included games have confirmed regular-season provenance. ")
            + "Opponent defensive ranking and exact-price value are not verified here."
        ),
    }
