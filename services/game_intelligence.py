from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from analytics.game_model_registry import (
    GAME_CONTEXT_CHALLENGER_VERSION,
    GAME_HISTORICAL_BASELINE_VERSION,
    GAME_MARKET_CHAMPION_VERSION,
)
from analytics.game_prediction import GamePrediction, predict_game
from data.providers.espn import fetch_final_game_outcomes
from data.providers.injury_feed import fetch_injuries
from repository.repositories.game_prediction_repository import GamePredictionRepository
from repository.repositories.team_history_repository import TeamHistoryRepository
from services import odds
from services.game_history_collection import collect_team_history
from services.game_team_features import team_history_features
from utils.ttl_cache import TTLMap

_MATCHUP_CACHE: TTLMap[tuple[str, str], dict] = TTLMap(max_size=128)


def predict_slate(sport: str, *, persist: bool = True) -> list[dict]:
    predictions: list[dict] = []
    sport_key = sport.upper()
    history_status = collect_team_history(sport_key) if persist else {"stored": 0, "mode": "read_only"}
    injuries = fetch_injuries(sport_key) if sport_key in {"NBA", "WNBA"} else []
    for game in odds.get_games(sport):
        features = build_game_features(game, sport, injuries=injuries)
        features["history_collection"] = history_status
        generated_at = datetime.now(UTC).isoformat()
        champion = predict_game(features, model_version=GAME_MARKET_CHAMPION_VERSION).snapshot() | {"generated_at": generated_at}
        historical = predict_game(features, model_version=GAME_HISTORICAL_BASELINE_VERSION).snapshot() | {"generated_at": generated_at}
        challenger = predict_game(features, model_version=GAME_CONTEXT_CHALLENGER_VERSION).snapshot() | {"generated_at": generated_at}
        if persist:
            champion = GamePredictionRepository.save(champion)
            historical = GamePredictionRepository.save(historical)
            challenger = GamePredictionRepository.save(challenger)
        predictions.append({
            "champion": champion,
            "historical_baseline": historical,
            "challenger": challenger,
            "comparison": _comparison(champion, challenger),
        })
    return predictions


def build_game_features(game: dict, sport: str, *, injuries: list[dict] | None = None) -> dict:
    summary = odds.summarize_game_odds(game)
    home = str(game.get("home_team") or "")
    market_home = float((summary.get("no_vig_probabilities") or {}).get(home) or 50.0) / 100.0
    spreads, totals = [], []
    for bookmaker in game.get("bookmakers") or []:
        for market in bookmaker.get("markets") or []:
            if market.get("key") == "spreads":
                for outcome in market.get("outcomes") or []:
                    if str(outcome.get("name") or "") == home and outcome.get("point") is not None:
                        spreads.append(-float(outcome["point"]))
            elif market.get("key") == "totals":
                for outcome in market.get("outcomes") or []:
                    if str(outcome.get("name") or "").lower() == "over" and outcome.get("point") is not None:
                        totals.append(float(outcome["point"]))
    quality = min(100.0, 35.0 + len(summary.get("bookmakers") or []) * 10.0 + (20.0 if totals else 0.0) + (15.0 if spreads else 0.0))
    game_start = str(game.get("commence_time") or "")
    historical = team_history_features(
        sport,
        home,
        str(game.get("away_team") or ""),
        game_start,
        TeamHistoryRepository.before(sport, game_start),
        injuries,
    )
    team_features = historical["team_features"]
    return {
        "sport": sport.upper(),
        "game_id": str(game.get("id") or ""),
        "game": f"{game.get('away_team', '')} @ {game.get('home_team', '')}",
        "away_team": str(game.get("away_team") or ""),
        "home_team": home,
        "game_start": game_start,
        "market_home_probability": market_home,
        "historical_home_probability": historical["historical_home_probability"],
        "historical_sample_size": historical["historical_sample_size"],
        "historical_margin_residual": historical["historical_margin_residual"],
        "context_home_probability_delta": _team_context_delta(team_features),
        "market_home_margin": median(spreads) if spreads else None,
        "market_total": median(totals) if totals else None,
        "expected_pace": _pace_from_total(sport, median(totals) if totals else None),
        "historical_pace": _team_pace(team_features),
        "data_quality_score": quality,
        "provider_freshness": "live" if summary.get("sportsbook_count") else "unavailable",
        "market_source": summary.get("source"),
        "market_snapshot": summary,
        "feature_treatments": {
            "moneyline": "baseline",
            "spread": "baseline",
            "total": "baseline",
            "historical_team_form": "shadow challenger feature built from settled pre-game outcomes",
            "injuries_weather_role": "verified injury reports are recorded; numeric injury effects remain shadow-only until role coverage is sufficient",
        },
        **historical,
    }


def latest_predictions(sport: str = "", limit: int = 50) -> list[dict]:
    return GamePredictionRepository.latest(sport=sport, limit=limit)


def latest_slate_predictions(sport: str = "", limit: int = 50) -> list[dict]:
    """Return one display row per game while preserving both model snapshots."""
    rows = latest_predictions(sport, max(limit * 4, 100))
    grouped: dict[str, dict[str, dict]] = {}
    order: list[str] = []
    for row in rows:
        game_key = str(row.get("game_id") or row.get("game") or "")
        if not game_key:
            continue
        if game_key not in grouped:
            grouped[game_key] = {}
            order.append(game_key)
        version = str(row.get("model_version") or "")
        grouped[game_key].setdefault(version, row)
    display_rows = []
    for game_key in order:
        versions = grouped[game_key]
        champion = versions.get(GAME_MARKET_CHAMPION_VERSION)
        historical = versions.get(GAME_HISTORICAL_BASELINE_VERSION)
        challenger = versions.get(GAME_CONTEXT_CHALLENGER_VERSION)
        primary = champion or challenger or next(iter(versions.values()), None)
        if primary is None:
            continue
        display_rows.append({
            "champion": champion or primary,
            "historical_baseline": historical,
            "challenger": challenger,
            "comparison": _comparison(champion or primary, challenger) if challenger else None,
        })
        if len(display_rows) >= limit:
            break
    return display_rows


def settle_recent_predictions(*, lookback_days: int = 3) -> dict:
    settled = 0
    checked = 0
    errors: list[str] = []
    today = date.today()
    dates: dict[str, set[date]] = {}
    for sport, start in GamePredictionRepository.pending_dates():
        try:
            day = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date()
        except ValueError:
            continue
        if day <= today:
            dates.setdefault(sport, set()).add(day)
    for sport, requested_dates in dates.items():
        for day in sorted(requested_dates)[:max(1, lookback_days * 4)]:
            try:
                outcomes = fetch_final_game_outcomes(sport, day)
            except Exception as exc:
                errors.append(f"{sport}: {exc}")
                continue
            checked += len(outcomes)
            for outcome in outcomes:
                settled += GamePredictionRepository.settle_outcome(outcome)
    return {"checked_games": checked, "settled_predictions": settled, "errors": errors}


def prediction_for_matchup(sport: str, game: str) -> dict | None:
    key = (sport.upper(), " ".join(str(game or "").lower().split()))
    cached = _MATCHUP_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        games = odds.get_games(sport)
    except Exception:
        return None
    matched = odds.find_game_odds(game, sport, games)
    if not matched:
        return None
    raw = next((row for row in games if str(row.get("id") or "") == str(matched.get("event_id") or "")), None)
    if raw is None:
        return None
    prediction = predict_game(build_game_features(raw, sport), model_version=GAME_CONTEXT_CHALLENGER_VERSION).snapshot()
    try:
        saved = GamePredictionRepository.save(prediction)
    except Exception:
        saved = prediction
    _MATCHUP_CACHE.set(key, saved, ttl=120.0)
    return saved


def _comparison(champion: dict, challenger: dict) -> dict:
    return {
        "home_probability_delta": round(float(challenger["home_win_probability"]) - float(champion["home_win_probability"]), 4),
        "margin_delta": round(float(challenger["expected_margin"]) - float(champion["expected_margin"]), 2),
        "challenger_shadow_only": True,
    }


def _pace_from_total(sport: str, total: float | None) -> float | None:
    if total is None:
        return None
    key = sport.upper()
    if key == "NBA":
        return round(100.0 * total / 222.0, 2)
    if key == "WNBA":
        return round(80.0 * total / 162.0, 2)
    return None


def _team_pace(features: dict) -> float | None:
    home = (features.get("home") or {}).get("estimated_pace")
    away = (features.get("away") or {}).get("estimated_pace")
    values = [float(value) for value in (home, away) if value is not None]
    return round(sum(values) / len(values), 2) if values else None


def _team_context_delta(features: dict) -> float:
    """Small, evidence-weighted residual; the market remains the production champion."""
    home = features.get("home") or {}
    away = features.get("away") or {}
    if not min(int(home.get("sample_size") or 0), int(away.get("sample_size") or 0)):
        return 0.0
    recent_delta = (_rate(home.get("recent_win_rate")) - _rate(away.get("recent_win_rate"))) * 0.08
    scoring_delta = (float(home.get("scoring_differential") or 0.0) - float(away.get("scoring_differential") or 0.0)) * 0.004
    split_delta = (
        _rate(home.get("home_win_rate")) - _rate(away.get("away_win_rate"))
    ) * 0.04
    home_rest = home.get("rest_days")
    away_rest = away.get("rest_days")
    rest_delta = max(-0.015, min(0.015, (float(home_rest or 0) - float(away_rest or 0)) * 0.003))
    return round(max(-0.06, min(0.06, recent_delta + scoring_delta + split_delta + rest_delta)), 4)


def _rate(value: object) -> float:
    return float(str(value)) if value is not None else 0.5
