from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from time import sleep

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from repository.database import Base
from repository.models.player_feature_model import PlayerFeatureModel
from repository.repositories import player_feature_repository as feature_module
from repository.repositories.player_feature_repository import PlayerFeatureRepository


def test_player_feature_store_materializes_and_reuses_verified_history(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'features.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(feature_module, "SessionLocal", session_local)
    monkeypatch.setattr(PlayerFeatureRepository, "_schema_ready", True)
    calls = []
    history = [
        {"player": "Player", "team": "A", "sport": "WNBA", "stat": "Points", "actual": value,
         "status": "played", "game": f"A@B-{index}", "game_date": f"2026-08-{index + 1:02d}", "minutes": 30 + index}
        for index, value in enumerate((20, 22, 24, 26, 28))
    ]
    monkeypatch.setattr(feature_module.FinalStatsRepository, "history", lambda *args, **kwargs: calls.append(args) or history)
    monkeypatch.setattr(feature_module.PlayerIdentityRepository, "resolve", lambda *args, **kwargs: {"id": 7})

    first = PlayerFeatureRepository.history("Player", "WNBA", "Points", team="A")
    second = PlayerFeatureRepository.history("Player", "WNBA", "Points", team="A")

    assert first == second
    assert len(calls) == 1
    with session_local() as session:
        row = session.query(PlayerFeatureModel).one()
        assert row.player_identity_id == 7
        assert row.sample_size == 5
        assert '"season_average": 24.0' in row.summary_json


def test_invalidation_expires_only_matching_feature(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'invalidation.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(feature_module, "SessionLocal", session_local)
    monkeypatch.setattr(PlayerFeatureRepository, "_schema_ready", True)
    now = datetime.now(UTC)
    with session_local() as session:
        session.add_all([
            PlayerFeatureModel(
                feature_key=PlayerFeatureRepository.feature_key("Player One", "WNBA", "Points"),
                normalized_player_key="playerone",
                player="Player One",
                sport="WNBA",
                stat="Points",
                materialized_at=now,
            ),
            PlayerFeatureModel(
                feature_key=PlayerFeatureRepository.feature_key("Player Two", "WNBA", "Rebounds"),
                normalized_player_key="playertwo",
                player="Player Two",
                sport="WNBA",
                stat="Rebounds",
                materialized_at=now,
            ),
        ])
        session.commit()

    expired = PlayerFeatureRepository.invalidate_segments([
        {"player": "Player One", "sport": "WNBA", "stat": "Points"},
    ])

    assert expired == 1
    assert PlayerFeatureRepository.get("Player One", "WNBA", "Points")["materialized_at"].startswith("1970-")
    assert not PlayerFeatureRepository.get("Player Two", "WNBA", "Rebounds")["materialized_at"].startswith("1970-")


def test_concurrent_materialization_reuses_one_segment(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(feature_module, "SessionLocal", session_local)
    monkeypatch.setattr(PlayerFeatureRepository, "_schema_ready", True)
    monkeypatch.setattr(feature_module.FinalStatsRepository, "history", lambda *args, **kwargs: [])
    monkeypatch.setattr(feature_module.PlayerIdentityRepository, "resolve", lambda *args, **kwargs: None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: PlayerFeatureRepository.materialize("Player", "MLB", "Hits"),
            range(2),
        ))

    assert len(results) == 2
    with session_local() as session:
        assert session.query(PlayerFeatureModel).count() == 1


def test_offer_materialization_uses_bounded_parallel_workers(monkeypatch):
    lock = Lock()
    active = 0
    peak = 0

    def history(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        sleep(0.03)
        with lock:
            active -= 1
        return []

    monkeypatch.setattr(PlayerFeatureRepository, "history", history)
    progress = []
    result = PlayerFeatureRepository.materialize_offers(
        [
            {"player": f"Player {index}", "sport": "MLB", "stat": "Hits"}
            for index in range(6)
        ],
        max_workers=3,
        progress=lambda completed, total: progress.append((completed, total)),
    )

    assert result["materialized"] == 6
    assert 2 <= peak <= 3
    assert progress[-1] == (6, 6)
