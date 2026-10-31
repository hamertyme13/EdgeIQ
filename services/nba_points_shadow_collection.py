"""Prospective, paper-only NBA Points forecasts from the archived provider board."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from contextlib import suppress
from time import monotonic

from analytics.probabilistic_forecast import forecast_prop
from repository.repositories.board_offer_repository import BoardOfferRepository
from repository.repositories.model_rehabilitation_repository import ModelRehabilitationRepository
from repository.repositories.team_history_repository import TeamHistoryRepository
from services.game_team_features import NBA_DEFENSE_CONTEXT_VERSION, opponent_points_allowed_context
from utils.entity_normalization import canonical_person_key
from utils.time import iso_utc, utc_now

_log = logging.getLogger(__name__)
BOARD_VERSION_PREFIX = "nba-points-board/"


def _opponent(offer: dict) -> str:
    matchup = str(offer.get("game") or "").replace(" ", "").upper().split("@")
    team = canonical_person_key(offer.get("team"))
    if len(matchup) != 2 or not team:
        return ""
    if canonical_person_key(matchup[0]) == team:
        return matchup[1]
    if canonical_person_key(matchup[1]) == team:
        return matchup[0]
    return ""


def needs_pregame_retry(cohort: dict, eastern_hour: int) -> bool:
    return not cohort.get("complete", False) and 0 <= eastern_hour < 22


def collect_nba_points_shadow(*, max_player_games: int = 250, max_runtime_seconds: int = 120) -> dict:
    board = BoardOfferRepository.nba_points_shadow_candidates()
    candidates = board["candidates"]
    budget = max(1, min(int(max_player_games), 500))
    runtime_budget = max(5, min(int(max_runtime_seconds), 150))
    started = monotonic()
    evidence_as_of = iso_utc(utc_now())
    team_games_by_start: dict[str, list[dict]] = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    failed = 0
    qualified = 0
    forecast_sources: Counter[str] = Counter()
    challenger_statuses: dict[str, Counter[str]] = {
        "minutes": Counter(),
        "shot_volume": Counter(),
    }
    verified_game_counts: Counter[int] = Counter()
    timed_out = False
    for offer in candidates[:budget]:
        if monotonic() - started >= runtime_budget:
            timed_out = True
            break
        try:
            forecast = forecast_prop(
                offer["player"], "NBA", "Points", offer["line"], "Over",
                game_time=offer["game_time"], team=offer["team"], game=offer["game"],
            )
        except Exception:
            failed += 1
            _log.exception("NBA Points shadow forecast failed for board observation %s", offer["board_observation_id"])
            continue
        version = f"{BOARD_VERSION_PREFIX}{forecast.model_version}"
        snapshot = forecast.snapshot()
        opponent = _opponent(offer)
        if opponent and isinstance(snapshot, dict):
            game_start = str(offer.get("game_time") or "")
            try:
                if game_start not in team_games_by_start:
                    team_games_by_start[game_start] = TeamHistoryRepository.before(
                        "NBA", game_start, as_of=evidence_as_of,
                    )
                defense = opponent_points_allowed_context(opponent, game_start, team_games_by_start[game_start])
                snapshot = {
                    **snapshot,
                    "features": {
                        **(snapshot.get("features") or {}),
                        "nba_points_opponent_defense": {
                            "model_version": NBA_DEFENSE_CONTEXT_VERSION,
                            "shadow_only": True,
                            "evidence_as_of": evidence_as_of,
                            "opponent": opponent,
                            "advantage_score": defense["advantage_score"],
                            "defensive_rank": defense["defensive_rank"],
                            "ranked_teams": defense["ranked_teams"],
                            "opponent_sample_size": defense["sample_size"],
                            "league_game_count": len(team_games_by_start[game_start]),
                            "source_games": defense["source_games"],
                        },
                    },
                }
            except Exception:
                _log.exception("NBA Points pregame defense context unavailable for board observation %s", offer["board_observation_id"])
        forecast_source = str(snapshot.get("source") or "unknown")
        forecast_sources[forecast_source] += 1
        qualified += forecast_source == "verified_history_distribution"
        features = snapshot.get("features") or {}
        for name, feature_key in (("minutes", "nba_points_minutes_shadow"),
                                  ("shot_volume", "nba_points_shot_volume_shadow")):
            evidence = features.get(feature_key) if isinstance(features, dict) else None
            status = str(evidence.get("status") or "not_recorded") if isinstance(evidence, dict) else "not_recorded"
            challenger_statuses[name][status] += 1
        if forecast_source == "market_prior":
            with suppress(TypeError, ValueError):
                verified_game_counts[int((snapshot.get("features") or {}).get("verified_games") or 0)] += 1
        grouped[version].append({
            **offer,
            "projection": forecast.projection,
            "probability": forecast.probability,
            "forecast_snapshot": snapshot,
            "forecast_model_version": forecast.model_version,
            "cohort_origin": "trackable_standard_board",
        })
    queued = 0
    created = 0
    for version, rows in grouped.items():
        result = ModelRehabilitationRepository.queue_shadow(
            rows, model_version=version, target=None, cohort_date=board["day"],
        )
        queued += result["queued"]
        created += result["created"]
    complete = bool(candidates) and not board["scan_limit_reached"] and len(candidates) <= budget and failed == 0 and not timed_out
    return {
        "day": board["day"],
        "status": "captured" if complete else "partial" if candidates else "no_fresh_trackable_board",
        "candidates": len(candidates),
        "forecasted": sum(len(rows) for rows in grouped.values()),
        "qualified_forecasts": qualified,
        "forecast_sources": dict(sorted(forecast_sources.items())),
        "challenger_statuses": {
            name: dict(sorted(statuses.items())) for name, statuses in challenger_statuses.items()
        },
        "market_prior_verified_game_counts": dict(sorted(verified_game_counts.items())),
        "qualification_note": (
            "No fresh, trackable NBA Points board was available."
            if not candidates else
            "The board was captured, but no history-based forecast qualified. Market-prior observations remain shadow-only until each player has at least five verified regular-season games."
            if candidates and qualified == 0 and forecast_sources.get("market_prior") else
            "Qualified forecasts remain research-only until chronological outcomes support them."
        ),
        "created": created,
        "queued": queued,
        "failed": failed,
        "timed_out": timed_out,
        "complete": complete,
        "source": "Fresh, standard, end-to-end-trackable NBA Points board offers; one Over line per player-game.",
    }
