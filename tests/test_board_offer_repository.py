from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.database as database
from analytics.hierarchical_calibration import calibrate_probability
from repository.database import Base
from repository.models.board_offer_observation_model import BoardOfferObservationModel
from repository.repositories import board_offer_repository as board_module
from repository.repositories.board_offer_repository import BoardOfferRepository


def _isolated_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'board.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'board.db'}")
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(board_module, "SessionLocal", session_local)
    Base.metadata.create_all(engine)
    BoardOfferRepository.invalidate_summary()
    return session_local


def _offer(line=20.5):
    return {
        "id": "offer-1",
        "player": "Paige Bueckers",
        "player_id": "provider-player-7",
        "league": "WNBA",
        "stat": "Points",
        "line": line,
        "direction": "Over",
        "platform": "PrizePicks",
        "game_id": "game-1",
        "game": "MIN @ DAL",
        "game_time": "2026-08-22T20:00:00Z",
        "line_offer_type": "standard",
        "multiplier": 3.0,
    }


def test_complete_board_capture_is_idempotent_within_minute(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    assert BoardOfferRepository.record_many([_offer()], "PrizePicks") == 1
    assert BoardOfferRepository.record_many([_offer()], "PrizePicks") == 0
    with session_local() as session:
        row = session.query(BoardOfferObservationModel).one()
        assert row.provider_player_id == "provider-player-7"
        assert row.game_id == "game-1"
        assert row.opening_line == 20.5
        assert row.provider_payload


def test_unchanged_offer_uses_hourly_checkpoints(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    first = datetime(2026, 9, 6, 14, 5, tzinfo=UTC)

    assert BoardOfferRepository.record_many([_offer()], "PrizePicks", captured_at=first) == 1
    assert BoardOfferRepository.record_many([_offer()], "PrizePicks", captured_at=first.replace(minute=55)) == 0
    assert BoardOfferRepository.record_many([_offer()], "PrizePicks", captured_at=first.replace(hour=15)) == 1


def test_complete_board_capture_deduplicates_same_offer_inside_batch(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    offer = _offer()

    assert BoardOfferRepository.record_many([offer, dict(offer)], "PrizePicks") == 1


def test_complete_board_summary_cache_invalidates_after_capture(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    first = datetime(2026, 9, 6, 14, tzinfo=UTC)
    BoardOfferRepository.record_many([_offer()], "PrizePicks", captured_at=first)

    fresh = BoardOfferRepository.summary()
    cached = BoardOfferRepository.summary()

    assert fresh["observations"] == 1
    assert fresh["cache"]["hit"] is False
    assert cached["cache"]["hit"] is True

    BoardOfferRepository.record_many([_offer()], "PrizePicks", captured_at=first.replace(hour=15))
    refreshed = BoardOfferRepository.summary()
    assert refreshed["observations"] == 2
    assert refreshed["cache"]["hit"] is False


def test_complete_board_capture_is_idempotent_across_concurrent_writers(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    monkeypatch.setattr(
        board_module.PlayerIdentityRepository,
        "capture_provider_players",
        lambda _rows, _provider: {"identity_ids": {}},
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = list(executor.map(lambda _index: BoardOfferRepository.record_many([_offer()], "PrizePicks"), range(2)))

    assert sum(created) == 1
    with session_local() as session:
        assert session.query(BoardOfferObservationModel).count() == 1


def test_analysis_enriches_board_without_removing_unselected_offers(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    BoardOfferRepository.record_many([_offer(), {**_offer(18.5), "id": "offer-2", "stat": "Rebounds"}], "PrizePicks")
    attached = BoardOfferRepository.attach_analysis({
        **_offer(),
        "sport": "WNBA",
        "projection": 22.1,
        "confidence": 61.2,
        "model_version": "edgeiq-test",
        "forecast_paid_eligible": False,
        "forecast_snapshot": {"reason": "Thin segment", "distribution": {"expected_minutes": 34}},
    })
    assert attached is True
    with session_local() as session:
        rows = session.query(BoardOfferObservationModel).all()
        assert len(rows) == 2
        assert sum(row.analyzed_at is not None for row in rows) == 1


def test_under_analysis_attaches_to_two_sided_provider_offer(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    BoardOfferRepository.record_many([_offer()], "PrizePicks")
    assert BoardOfferRepository.attach_analysis({
        **_offer(), "sport": "WNBA", "direction": "Under",
        "projection": 18.0, "confidence": 60.0,
        "forecast_snapshot": {"distribution": {}},
    }) is True
    with session_local() as session:
        row = session.query(BoardOfferObservationModel).one()
        assert row.projection == 18.0
        assert row.direction == "Under"


def test_complete_board_builds_due_final_stat_targets_without_future_offers(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    now = datetime(2026, 8, 24, 18, tzinfo=UTC)
    due = {**_offer(), "game_time": "2026-08-24T14:00:00Z", "end_to_end_confirmed": True}
    future = {**_offer(), "id": "future", "game_id": "game-2", "game": "NY @ LV", "game_time": "2026-08-24T20:00:00Z", "end_to_end_confirmed": True}
    BoardOfferRepository.record_many([due, future], "PrizePicks", captured_at=now)

    entries = BoardOfferRepository.settlement_entries(now=now)

    assert len(entries) == 1
    assert len(entries[0]["props"]) == 1
    assert entries[0]["props"][0]["game"] == "MIN @ DAL"


def test_complete_board_settlement_targets_each_market_once(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    first = datetime(2026, 8, 24, 14, tzinfo=UTC)
    offer = {**_offer(), "game_time": "2026-08-24T10:00:00Z", "end_to_end_confirmed": True}
    BoardOfferRepository.record_many([offer], "PrizePicks", captured_at=first)
    BoardOfferRepository.record_many([offer], "PrizePicks", captured_at=first.replace(hour=15))

    entries = BoardOfferRepository.settlement_entries(now=datetime(2026, 8, 24, 18, tzinfo=UTC))

    assert len(entries) == 1
    assert len(entries[0]["props"]) == 1
    with session_local() as session:
        assert session.query(BoardOfferObservationModel).count() == 2


def test_verified_result_settles_every_line_snapshot_for_market(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    first = datetime(2026, 8, 24, 14, tzinfo=UTC)
    BoardOfferRepository.record_many([_offer(20.5)], "PrizePicks", captured_at=first)
    BoardOfferRepository.record_many([_offer(21.5)], "PrizePicks", captured_at=first.replace(hour=15))
    calls = []

    def final_result(payload):
        calls.append(payload)
        return {"actual": 21.0, "source": "verified-test", "status": "played"}

    monkeypatch.setattr(board_module.FinalStatsRepository, "find_result", final_result)

    result = BoardOfferRepository.settle_pending()

    assert result == {"attempted": 1, "settled": 1, "observations_settled": 2, "unresolved": 0}
    assert len(calls) == 1
    with session_local() as session:
        rows = session.query(BoardOfferObservationModel).order_by(BoardOfferObservationModel.line).all()
        assert [row.outcome for row in rows] == ["Win", "Loss"]
        assert {row.actual for row in rows} == {21.0}
        assert {row.closing_line for row in rows} == {21.5}


def test_settlement_reuses_final_fact_across_directions(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    captured = datetime(2026, 8, 24, 14, tzinfo=UTC)
    BoardOfferRepository.record_many(
        [_offer(20.5), {**_offer(20.5), "id": "offer-under", "direction": "Under"}],
        "PrizePicks",
        captured_at=captured,
    )
    calls = []
    monkeypatch.setattr(
        board_module.FinalStatsRepository,
        "find_result",
        lambda payload: calls.append(payload) or {
            "actual": 21.0,
            "source": "verified-test",
            "status": "played",
        },
    )

    result = BoardOfferRepository.settle_pending()

    assert result["attempted"] == 2
    assert result["settled"] == 2
    assert len(calls) == 1
    with session_local() as session:
        rows = session.query(BoardOfferObservationModel).order_by(BoardOfferObservationModel.direction).all()
        assert {row.outcome for row in rows} == {"Win", "Loss"}


def test_complete_board_settlement_does_not_query_future_games(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    now = datetime(2026, 8, 24, 18, tzinfo=UTC)
    due = {**_offer(), "game_time": "2026-08-24T14:00:00Z", "end_to_end_confirmed": True}
    future = {
        **_offer(),
        "id": "future",
        "game_id": "game-2",
        "game": "NY @ LV",
        "game_time": "2026-08-24T20:00:00Z",
        "end_to_end_confirmed": True,
    }
    BoardOfferRepository.record_many([due, future], "PrizePicks", captured_at=now)
    calls = []
    monkeypatch.setattr(
        board_module.FinalStatsRepository,
        "find_result",
        lambda payload: calls.append(payload) or None,
    )

    result = BoardOfferRepository.settle_pending(now=now)

    assert result["attempted"] == 1
    assert result["unresolved"] == 1
    assert len(calls) == 1
    assert calls[0]["game"] == "MIN @ DAL"
    with session_local() as session:
        due_row = session.query(BoardOfferObservationModel).filter_by(game="MIN @ DAL").one()
        assert due_row.settlement_attempts == 1
        assert due_row.settlement_block_reason == "Waiting for a verified final box score."
        assert due_row.next_settlement_retry_at is not None
    retry_status = BoardOfferRepository.summary()["settlement_retry"]
    assert retry_status["items"][0]["player"] == "Paige Bueckers"
    assert retry_status["items"][0]["attempts"] == 1
    assert retry_status["items"][0]["blocking_reason"] == "Waiting for a verified final box score."

    waiting = BoardOfferRepository.settle_pending(now=now.replace(minute=20))
    assert waiting["attempted"] == 0
    assert len(calls) == 1
    assert BoardOfferRepository.settlement_entries(now=now.replace(minute=20)) == []

    assert len(BoardOfferRepository.settlement_entries(now=now.replace(minute=31))[0]["props"]) == 1
    retry = BoardOfferRepository.settle_pending(now=now.replace(minute=31))
    assert retry["attempted"] == 1
    assert len(calls) == 2
    with session_local() as session:
        due_row = session.query(BoardOfferObservationModel).filter_by(game="MIN @ DAL").one()
        assert due_row.settlement_attempts == 2


def test_complete_board_evidence_compares_analyzed_and_unselected_markets(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    BoardOfferRepository.record_many([_offer(), {**_offer(18.5), "id": "offer-2", "stat": "Rebounds"}], "PrizePicks")
    BoardOfferRepository.attach_analysis({
        **_offer(), "sport": "WNBA", "projection": 22.0, "confidence": 60.0,
        "model_version": "edgeiq-v2.4", "forecast_snapshot": {"distribution": {}},
    })
    with session_local() as session:
        rows = session.query(BoardOfferObservationModel).order_by(BoardOfferObservationModel.id).all()
        rows[0].outcome, rows[0].actual, rows[0].closing_line = "Win", 24.0, 21.0
        rows[1].outcome, rows[1].actual, rows[1].closing_line = "Loss", 17.0, 18.0
        session.commit()

    report = BoardOfferRepository.evidence_report()

    assert report["coverage"]["independent_offers"] == 2
    assert report["coverage"]["settled_offers"] == 2
    assert report["model"]["samples"] == 1
    assert report["baseline"]["samples"] == 1
    assert report["selection_lift"] == 100.0
    assert report["by_model_version"][0]["name"] == "edgeiq-v2.4"


def test_complete_board_evidence_cache_invalidates_after_capture(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    BoardOfferRepository.record_many([_offer()], "PrizePicks")

    fresh = BoardOfferRepository.evidence_report()
    cached = BoardOfferRepository.evidence_report()

    assert fresh["coverage"]["independent_offers"] == 1
    assert fresh["cache"]["hit"] is False
    assert cached["cache"]["hit"] is True

    BoardOfferRepository.record_many(
        [{**_offer(18.5), "id": "offer-2", "stat": "Rebounds"}],
        "PrizePicks",
    )
    refreshed = BoardOfferRepository.evidence_report()
    assert refreshed["coverage"]["independent_offers"] == 2
    assert refreshed["cache"]["hit"] is False


def test_segment_requires_one_hundred_independent_results_for_paid_mode():
    rows = [
        {
            "player": f"Player {index}", "sport": "WNBA", "stat": "points",
            "platform": "prizepicks", "direction": "over", "projection_source": "model",
                "line": float(index), "game": f"A{index} @ B", "game_time": f"2026-08-{(index % 20) + 1:02d}",
                "result": "Win" if index % 2 else "Loss",
                "outcome_source": "espn",
        }
        for index in range(100)
    ]
    below = calibrate_probability(
        0.60, sport="WNBA", stat="Points", provider="PrizePicks",
        direction="Over", projection_source="model", rows=rows[:99],
    )
    ready = calibrate_probability(
        0.60, sport="WNBA", stat="Points", provider="PrizePicks",
        direction="Over", projection_source="model", rows=rows,
    )
    assert below["paid_eligible"] is False
    assert below["segment_maturity"] == "thin"
    assert ready["segment_sample_size"] == 100
    assert ready["segment_maturity"] == "calibrated"
