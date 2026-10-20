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


def test_background_job_claim_is_atomic_across_workers(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'claims.db'}", connect_args={"timeout": 5})
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(job_module, "SessionLocal", session_local)
    monkeypatch.setattr(BackgroundJobRepository, "_schema_ready", True)
    barrier = threading.Barrier(2)

    def claim(number):
        job = {
            "job_id": f"refresh-{number}", "kind": "provider_refresh",
            "dedupe_key": "provider-refresh", "status": "queued",
            "_process_id": os.getpid(),
        }
        barrier.wait(timeout=5)
        return BackgroundJobRepository.claim(job)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(claim, 1)
        second = pool.submit(claim, 2)
        results = [first.result(timeout=10), second.result(timeout=10)]

    assert sum(result is None for result in results) == 1
    assert len(BackgroundJobRepository.recent()) == 1
    assert next(result for result in results if result is not None)["dedupe_key"] == "provider-refresh"
import os
import threading
from concurrent.futures import ThreadPoolExecutor
