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
        assert session.query(BoardOfferObservationModel).one().projection == 18.0


def test_segment_requires_one_hundred_independent_results_for_paid_mode():
    rows = [
        {
            "player": f"Player {index}", "sport": "WNBA", "stat": "points",
            "platform": "prizepicks", "direction": "over", "projection_source": "model",
            "line": float(index), "game": f"A{index} @ B", "game_time": f"2026-08-{(index % 20) + 1:02d}",
            "result": "Win" if index % 2 else "Loss",
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
