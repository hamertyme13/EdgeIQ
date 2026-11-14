"""Read-only official-game and roster audit of past-due NBA Points shadow offers."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date

from data.providers.espn import fetch_final_game_outcomes, fetch_final_stats, fetch_game_times
from repository.database import SessionLocal
from repository.models.board_offer_observation_model import BoardOfferObservationModel
from repository.models.shadow_prediction_model import ShadowPredictionModel
from repository.repositories.final_stats_repository import _TEAM_ALIASES, _game_key
from repository.repositories.model_rehabilitation_repository import _past_game_completion_window
from scripts.audit_nba_points_shadow_pending import _eastern_day
from utils.entity_normalization import canonical_matchup_key, canonical_person_key


def classify_offers(offers: list[dict], games: list[dict], outcomes: list[dict], finals: list[dict]) -> list[dict]:
    """Diagnose identity coverage; never infer a win, loss, or DNP from absence."""
    scheduled = {_game_key(row.get("game")) for row in games}
    completed = {_game_key(row.get("game")) for row in outcomes}
    points = [row for row in finals if row.get("sport") == "NBA" and row.get("stat") == "Points"]
    by_player: dict[str, list[dict]] = defaultdict(list)
    for row in points:
        by_player[canonical_person_key(row.get("player"))].append(row)
    diagnosed = []
    for offer in offers:
        game = _game_key(offer.get("game"))
        player_rows = by_player.get(canonical_person_key(offer.get("player")), [])
        exact = [row for row in player_rows if _game_key(row.get("game")) == game]
        if not game or not canonical_person_key(offer.get("player")):
            reason = "incomplete_offer_identity"
        elif game not in scheduled:
            reason = "game_absent_from_official_schedule"
        elif game not in completed:
            reason = "game_not_in_official_final_outcomes"
        elif exact:
            reason = "exact_player_game_final_available"
        elif player_rows:
            reason = "player_in_other_game_that_day"
        else:
            reason = "player_absent_from_official_points_roster"
        diagnosed.append({
            "player": offer.get("player"), "team": offer.get("team"), "game": offer.get("game"),
            "game_day": _eastern_day(offer.get("game_time")), "reason": reason,
            "other_game": player_rows[0].get("game") if reason == "player_in_other_game_that_day" else None,
            "provider_player_id_present": bool(offer.get("provider_player_id")),
            "provider_game_id_present": bool(offer.get("provider_game_id")),
        })
    return diagnosed


def annotate_other_appearances(diagnosed: list[dict], official_points: list[dict]) -> None:
    """Add context from other checked dates without rewriting an offered game."""
    other_games: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in official_points:
        other_games[canonical_person_key(row.get("player"))].add(
            (str(row.get("team") or ""), str(row.get("game_date") or ""))
        )
    for row in diagnosed:
        appearances = other_games.get(canonical_person_key(row["player"]), set())
        teams = {team for team, _ in appearances if team}
        offered_team = canonical_matchup_key(row.get("team"), _TEAM_ALIASES)
        row["official_appearances_on_checked_dates"] = len(appearances)
        row["official_teams_on_checked_dates"] = sorted(teams)
        row["seen_with_offered_team_on_other_date"] = bool(
            offered_team and any(canonical_matchup_key(team, _TEAM_ALIASES) == offered_team for team in teams)
        )


def research(*, max_dates: int = 20) -> dict:
    with SessionLocal() as session:
        records = session.query(ShadowPredictionModel).filter(
            ShadowPredictionModel.model_version.like("nba-points-board/%"),
            ShadowPredictionModel.status == "shadow_pending",
        ).all()
        snapshots = []
        for record in records:
            if not _past_game_completion_window(record.game_time):
                continue
            try:
                snapshot = json.loads(record.feature_snapshot or "{}")
            except (TypeError, ValueError):
                snapshot = {}
            snapshots.append((record, snapshot))
        observation_ids = [snapshot.get("board_observation_id") for _, snapshot in snapshots
                           if snapshot.get("board_observation_id")]
        board = {
            row.id: row for row in session.query(BoardOfferObservationModel)
            .filter(BoardOfferObservationModel.id.in_(observation_ids)).all()
        } if observation_ids else {}
        offers = []
        for record, snapshot in snapshots:
            observation = board.get(snapshot.get("board_observation_id"))
            try:
                payload = json.loads(observation.provider_payload or "{}") if observation else {}
            except (TypeError, ValueError):
                payload = {}
            offers.append({
                "player": record.player, "team": record.team, "game": record.game,
                "game_time": record.game_time, "model_version": record.model_version,
                "provider_player_id": snapshot.get("provider_player_id") or (observation.provider_player_id if observation else ""),
                "provider_game_id": snapshot.get("provider_game_id") or payload.get("provider_game_id"),
            })
    by_date: dict[str, list[dict]] = defaultdict(list)
    for offer in offers:
        day = _eastern_day(offer["game_time"])
        if day:
            by_date[day].append(offer)
    dates = sorted(by_date, reverse=True)[:max(1, min(int(max_dates), 31))]
    diagnosed = []
    errors = []
    official_points: list[dict] = []
    for day in dates:
        try:
            game_day = date.fromisoformat(day)
            games = fetch_game_times("NBA", game_day)
            outcomes = fetch_final_game_outcomes("NBA", game_day)
            finals = fetch_final_stats("NBA", game_day)
            official_points.extend(row for row in finals if row.get("sport") == "NBA" and row.get("stat") == "Points")
            diagnosed.extend(classify_offers(by_date[day], games, outcomes, finals))
        except (RuntimeError, ValueError, OSError) as exc:
            errors.append({"day": day, "error": str(exc)})
    annotate_other_appearances(diagnosed, official_points)
    return {
        "past_due": len(offers), "dates_checked": dates,
        "classified": len(diagnosed),
        "by_reason": dict(sorted(Counter(row["reason"] for row in diagnosed).items())),
        "by_model_version": dict(sorted(Counter(row["model_version"] for row in offers).items())),
        "provider_player_id_present": sum(row["provider_player_id_present"] for row in diagnosed),
        "provider_game_id_present": sum(row["provider_game_id_present"] for row in diagnosed),
        "players_seen_elsewhere_on_checked_dates": sum(bool(row["official_appearances_on_checked_dates"]) for row in diagnosed),
        "players_never_seen_on_checked_dates": sum(not row["official_appearances_on_checked_dates"] for row in diagnosed),
        "seen_with_offered_team_on_other_date": sum(row["seen_with_offered_team_on_other_date"] for row in diagnosed),
        "examples": diagnosed[:30], "errors": errors,
        "note": "Read-only coverage audit. A missing roster row is not a DNP or loss.",
    }


if __name__ == "__main__":
    print(json.dumps(research(), indent=2))
