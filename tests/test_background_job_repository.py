from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from repository.database import Base
from repository.repositories import background_job_repository as job_module
from repository.repositories.background_job_repository import BackgroundJobRepository


def test_background_job_repository_round_trips_and_recovers(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(job_module, "SessionLocal", session_local)
    monkeypatch.setattr(BackgroundJobRepository, "_schema_ready", True)
    job = {
        "job_id": "refresh-1",
        "kind": "provider_refresh",
        "label": "Provider refresh",
        "dedupe_key": "provider-refresh",
        "status": "running",
        "progress": 35,
        "phase": "Loading lines",
        "created_at": "2026-08-29T00:00:00+00:00",
        "started_at": "2026-08-29T00:00:01+00:00",
        "completed_at": "",
        "cancel_requested": False,
        "result": {},
        "error": "",
    }

    BackgroundJobRepository.save(job)
    recovered = BackgroundJobRepository.recover_interrupted("2026-08-29T01:00:00+00:00")
    stored = BackgroundJobRepository.recent(10)[0]

    assert len(recovered) == 1
    assert stored["job_id"] == "refresh-1"
    assert stored["status"] == "failed"
    assert stored["progress"] == 100
    assert "restart" in stored["error"]
