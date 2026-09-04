from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.final_stats_repository as final_stats_module
import repository.repositories.player_identity_repository as identity_module
from repository.database import Base
from repository.models.final_player_stat_model import FinalPlayerStatModel
from repository.models.player_feature_model import PlayerFeatureModel  # noqa: F401
from repository.repositories.final_stats_repository import FinalStatsRepository
from repository.repositories.player_identity_repository import PlayerIdentityRepository


def _isolated_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'final-stats.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(final_stats_module, "SessionLocal", session_local)
    monkeypatch.setattr(identity_module, "SessionLocal", session_local)
    monkeypatch.setattr(PlayerIdentityRepository, "_schema_ready", True)
    Base.metadata.create_all(engine)
    return session_local


def test_final_stat_sync_updates_canonical_record_without_duplicate(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    row = {
        "player": "Azura Stevens",
        "team": "LAS",
        "sport": "WNBA",
        "stat": "Points",
        "game": "LAS @ MIN",
        "game_date": "2026-08-20",
        "actual": 14,
        "status": "played",
        "source": "ESPN",
        "provider_player_id": "4433408",
    }
    first = FinalStatsRepository.upsert_many_report([row, dict(row)])
    second = FinalStatsRepository.upsert_many_report([{**row, "player": "Azurá Stevens", "actual": 16}])

    with session_local() as session:
        records = session.query(FinalPlayerStatModel).all()
    assert first == {"processed": 1, "inserted": 1, "updated": 0, "duplicates_removed": 0}
    assert second["inserted"] == 0
    assert second["updated"] == 1
    assert len(records) == 1
    assert records[0].actual == 16


def test_sport_cleanup_removes_existing_identity_duplicates(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    identity = PlayerIdentityRepository.resolve("Test Player", "NFL", "BUF")
    with session_local() as session:
        for player in ("Test Player", "Tést Player"):
            session.add(FinalPlayerStatModel(
                player=player,
                player_identity_id=identity["id"],
                team="BUF",
                sport="NFL",
                stat="Receiving Yards",
                game="BUF @ NYJ",
                game_date="2026-09-01",
                actual=72,
                status="played",
                source="ESPN",
            ))
        session.commit()

    assert FinalStatsRepository.deduplicate_sport("NFL") == 1
    with session_local() as session:
        assert session.query(FinalPlayerStatModel).count() == 1


def test_sport_cleanup_keeps_verified_result_over_newer_live_row(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    identity = PlayerIdentityRepository.resolve("Verified Player", "MLB", "NYM")
    shared = {
        "player": "Verified Player",
        "player_identity_id": identity["id"],
        "team": "NYM",
        "sport": "MLB",
        "stat": "Hits",
        "game": "NYM @ PHI",
        "game_date": "2026-09-02",
        "source": "ESPN",
    }
    with session_local() as session:
        session.add(FinalPlayerStatModel(**shared, actual=2, status="played"))
        session.flush()
        verified_id = session.query(FinalPlayerStatModel.id).scalar()
        session.add(FinalPlayerStatModel(**shared, actual=0, status="live"))
        session.commit()

    assert FinalStatsRepository.deduplicate_sport("MLB") == 1
    with session_local() as session:
        records = session.query(FinalPlayerStatModel).all()
    assert len(records) == 1
    assert records[0].id == verified_id
    assert records[0].status == "played"
    assert records[0].actual == 2
