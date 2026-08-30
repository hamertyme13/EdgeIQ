from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.database as database
from analytics.hierarchical_calibration import calibrate_probability
from repository.database import Base
from repository.repositories import model_rehabilitation_repository as rehabilitation_module
from repository.repositories import settings_repository as settings_module
from repository.repositories.model_rehabilitation_repository import ModelRehabilitationRepository


def _isolated_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rehabilitation.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'rehabilitation.db'}")
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(rehabilitation_module, "SessionLocal", session_local)
    monkeypatch.setattr(settings_module, "SessionLocal", session_local)
    Base.metadata.create_all(engine)
    return session_local


def test_uncalibrated_probability_is_capped_below_extreme_confidence():
    result = calibrate_probability(0.98, sport="WNBA", stat="Points", provider="PrizePicks", direction="Over", projection_source="provider", rows=[])
    assert result["probability"] == 65.0
    assert result["paid_eligible"] is False


def test_shadow_ledger_uses_daily_cohorts_and_does_not_release_unsettled(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    prop = {"player": "Player One", "sport": "WNBA", "stat": "Points", "line": 20.5, "direction": "Over", "platform": "PrizePicks", "game": "A @ B", "game_time": "2026-08-09T20:00:00Z", "confidence": 62}
    first = ModelRehabilitationRepository.queue_shadow([prop], model_version="shadow-test", target=1, cohort_date="2026-08-09")
    second = ModelRehabilitationRepository.queue_shadow([prop], model_version="shadow-test", target=1, cohort_date="2026-08-10")
    assert first["created"] == second["created"] == 1
    assert ModelRehabilitationRepository.shadow_status()["release_ready"] is False
    assert ModelRehabilitationRepository.shadow_status()["cohorts"] == 2


def test_recommendation_snapshots_are_immutable(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    first = ModelRehabilitationRepository.save_feed({"feed": {"platform": "PrizePicks"}, "props": [{"line": 10.5}]})
    second = ModelRehabilitationRepository.save_feed({"feed": {"platform": "Underdog"}, "props": [{"line": 11.5}]})
    history = ModelRehabilitationRepository.snapshot_history()
    assert first["snapshot_id"] != second["snapshot_id"]
    assert len(history) == 2


def test_actionable_rows_receive_the_persisted_snapshot_identity(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    saved = ModelRehabilitationRepository.save_feed({
        "feed": {"platform": "PrizePicks", "purpose": "Shared actionable recommendation feed."},
        "opportunity_feed": {"opportunities": [{"player": "Player One"}]},
    }, model_version="edgeiq-test")
    history = ModelRehabilitationRepository.snapshot_history(1)[0]
    opportunity = history["payload"]["opportunity_feed"]["opportunities"][0]
    assert opportunity["recommendation_snapshot_id"] == saved["snapshot_id"]
    assert opportunity["model_version"] == "edgeiq-test"


def test_snapshot_automatically_queues_complete_props_for_shadow_evidence(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    saved = ModelRehabilitationRepository.save_feed({
        "feed": {"platform": "PrizePicks", "purpose": "recommendation_feed"},
        "props": [{
            "player": "College QB", "team": "AAA", "sport": "NCAAF",
            "stat": "Passing Yards", "line": 275.5, "direction": "Over",
            "platform": "PrizePicks", "game": "AAA @ BBB",
            "game_time": "2026-08-30T20:00:00Z", "confidence": 58,
        }],
    }, model_version="edgeiq-test")

    assert saved["evidence_capture"]["eligible_props"] == 1
    assert saved["evidence_capture"]["created"] == 1
    assert ModelRehabilitationRepository.shadow_rows()[0]["sport"] == "NCAAF"

    second = ModelRehabilitationRepository.save_feed({
        "props": [{
            "player": "College Receiver", "team": "BBB", "sport": "NCAAF",
            "stat": "Receiving Yards", "line": 72.5, "direction": "Over",
            "platform": "PrizePicks", "game": "AAA @ BBB",
            "game_time": "2026-08-30T20:00:00Z", "confidence": 57,
        }],
    }, model_version="edgeiq-test")
    assert second["evidence_capture"]["created"] == 1
    assert len(ModelRehabilitationRepository.shadow_rows()) == 2


def test_shadow_settlement_uses_verified_result_evidence(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    ModelRehabilitationRepository._legacy_migrated = True
    ModelRehabilitationRepository.queue_shadow([{
        "player": "Player One", "sport": "WNBA", "stat": "Points", "line": 20.5,
        "direction": "Over", "platform": "PrizePicks", "game": "A @ B",
        "game_time": "2026-08-08T20:00:00Z", "confidence": 62,
    }], model_version="shadow-test", target=1, cohort_date="2026-08-08")
    monkeypatch.setattr(
        "repository.repositories.model_rehabilitation_repository.FinalStatsRepository.find_result",
        lambda _prop: {"actual": 24.0, "status": "played", "source": "ESPN public"},
    )
    result = ModelRehabilitationRepository.settle_pending()
    assert result["settled"] == 1
    assert ModelRehabilitationRepository.shadow_rows()[0]["result"] == "Win"
