from types import SimpleNamespace

from services import nba_points_shadow_collection as collection


def test_board_cohort_forecasts_once_per_candidate_without_provider_refresh(monkeypatch):
    offers = [
        {"player": "First Player", "team": "BOS", "sport": "NBA", "stat": "Points",
         "line": 20.5, "direction": "Over", "platform": "PrizePicks", "game": "BOS @ NYK",
         "game_time": "2026-10-24T23:00:00Z", "board_observation_id": 1,
         "board_captured_at": "2026-10-24T12:00:00+00:00"},
        {"player": "Second Player", "team": "NYK", "sport": "NBA", "stat": "Points",
         "line": 18.5, "direction": "Over", "platform": "PrizePicks", "game": "BOS @ NYK",
         "game_time": "2026-10-24T23:00:00Z", "board_observation_id": 2,
         "board_captured_at": "2026-10-24T12:00:00+00:00"},
    ]
    monkeypatch.setattr(collection.BoardOfferRepository, "nba_points_shadow_candidates", lambda: {
        "candidates": offers, "day": "2026-10-24", "scan_limit_reached": False,
    })
    calls = []

    def forecast(player, sport, stat, line, direction, **kwargs):
        calls.append((player, sport, stat, line, direction))
        return SimpleNamespace(
            projection=line + 1, probability=58, model_version="champion-v1",
            snapshot=lambda: {"source": "verified_history_distribution", "feature_as_of": "2026-10-24T12:00:00Z"},
        )

    queued = []

    def queue(rows, **kwargs):
        queued.append((rows, kwargs))
        return {"queued": len(rows), "created": len(rows)}

    monkeypatch.setattr(collection, "forecast_prop", forecast)
    monkeypatch.setattr(collection.ModelRehabilitationRepository, "queue_shadow", queue)
    history_calls = []
    def prior_games(sport, game_start, *, as_of=None):
        history_calls.append((sport, game_start, as_of))
        return []
    monkeypatch.setattr(collection.TeamHistoryRepository, "before", prior_games)

    result = collection.collect_nba_points_shadow()

    assert len(calls) == 2
    assert all(call[-1] == "Over" for call in calls)
    assert queued[0][1] == {"model_version": "nba-points-board/champion-v1", "target": None, "cohort_date": "2026-10-24"}
    assert all(row["cohort_origin"] == "trackable_standard_board" for row in queued[0][0])
    assert result["created"] == 2
    assert result["qualified_forecasts"] == 2
    assert result["forecast_sources"] == {"verified_history_distribution": 2}
    assert result["challenger_statuses"]["minutes"] == {"not_recorded": 2}
    assert result["complete"] is True
    assert len(history_calls) == 1
    assert history_calls[0][2]
    assert all(row["forecast_snapshot"]["features"]["nba_points_opponent_defense"]["shadow_only"] for row in queued[0][0])


def test_board_cohort_reports_truncation(monkeypatch):
    monkeypatch.setattr(collection.BoardOfferRepository, "nba_points_shadow_candidates", lambda: {
        "candidates": [
            {"player": player, "team": "BOS", "line": 20.5, "game": "BOS @ NYK",
             "game_time": "2026-10-24T23:00:00Z", "board_observation_id": index}
            for index, player in enumerate(("One", "Two"), start=1)
        ],
        "day": "2026-10-24", "scan_limit_reached": False,
    })
    monkeypatch.setattr(collection, "forecast_prop", lambda *args, **kwargs: SimpleNamespace(
        projection=20, probability=50, model_version="prior",
        snapshot=lambda: {"source": "market_prior"},
    ))
    monkeypatch.setattr(collection.ModelRehabilitationRepository, "queue_shadow", lambda rows, **kwargs: {
        "queued": len(rows), "created": len(rows),
    })

    result = collection.collect_nba_points_shadow(max_player_games=1)

    assert result["forecasted"] == 1
    assert result["complete"] is False
    assert result["forecast_sources"] == {"market_prior": 1}
    assert "shadow-only" in result["qualification_note"]


def test_board_cohort_reports_each_locked_challenger_status(monkeypatch):
    monkeypatch.setattr(collection.BoardOfferRepository, "nba_points_shadow_candidates", lambda: {
        "candidates": [{"player": "One", "team": "BOS", "game": "BOS @ NYK",
                        "line": 20.5, "game_time": "2026-10-24T23:00:00Z",
                        "board_observation_id": 1}],
        "day": "2026-10-24", "scan_limit_reached": False,
    })
    monkeypatch.setattr(collection, "forecast_prop", lambda *args, **kwargs: SimpleNamespace(
        projection=21, probability=55, model_version="champion-v1",
        snapshot=lambda: {"source": "verified_history_distribution", "features": {
            "nba_points_minutes_shadow": {"status": "awaiting_holdout"},
            "nba_points_shot_volume_shadow": {"status": "insufficient_verified_shot_volume"},
        }},
    ))
    monkeypatch.setattr(collection.ModelRehabilitationRepository, "queue_shadow", lambda rows, **kwargs: {
        "queued": len(rows), "created": len(rows),
    })
    monkeypatch.setattr(collection.TeamHistoryRepository, "before", lambda *args, **kwargs: [])

    result = collection.collect_nba_points_shadow()

    assert result["challenger_statuses"] == {
        "minutes": {"awaiting_holdout": 1},
        "shot_volume": {"insufficient_verified_shot_volume": 1},
    }


def test_empty_fresh_board_is_reported_as_incomplete(monkeypatch):
    monkeypatch.setattr(collection.BoardOfferRepository, "nba_points_shadow_candidates", lambda: {
        "candidates": [], "day": "2026-10-24", "scan_limit_reached": False,
    })

    result = collection.collect_nba_points_shadow()

    assert result["status"] == "no_fresh_trackable_board"
    assert result["complete"] is False
    assert result["qualified_forecasts"] == 0
    assert collection.needs_pregame_retry(result, 9) is True
    assert collection.needs_pregame_retry(result, 13) is True
    assert collection.needs_pregame_retry(result, 21) is True
    assert collection.needs_pregame_retry(result, 22) is False
    assert collection.needs_pregame_retry({"complete": True}, 9) is False


def test_collection_stops_at_runtime_budget_without_claiming_complete(monkeypatch):
    monkeypatch.setattr(collection.BoardOfferRepository, "nba_points_shadow_candidates", lambda: {
        "candidates": [{"player": "One", "line": 20.5}],
        "day": "2026-10-24", "scan_limit_reached": False,
    })
    ticks = iter((0, 200))
    monkeypatch.setattr(collection, "monotonic", lambda: next(ticks))

    result = collection.collect_nba_points_shadow(max_runtime_seconds=120)

    assert result["timed_out"] is True
    assert result["forecasted"] == 0
    assert result["complete"] is False
