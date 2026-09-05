import os
from threading import Event

from services.background_jobs import BackgroundJobManager


class MemoryJobRepository:
    def __init__(self, jobs=None):
        self.jobs = {job["job_id"]: dict(job) for job in (jobs or [])}

    def save(self, job):
        self.jobs[job["job_id"]] = dict(job)

    def recent(self, limit):
        return list(self.jobs.values())[-limit:]

    def get(self, job_id):
        return self.jobs.get(job_id)

    def active(self, dedupe_key):
        return next((
            job for job in reversed(list(self.jobs.values()))
            if job.get("dedupe_key") == dedupe_key
            and job.get("status") in {"queued", "running", "canceling"}
            and int(job.get("_process_id") or 0) == os.getpid()
        ), None)

    def recover_interrupted(self, completed_at):
        recovered = []
        for job in self.jobs.values():
            if job["status"] in {"queued", "running", "canceling"}:
                if int(job.get("_process_id") or 0) == os.getpid():
                    continue
                job.update(
                    status="failed",
                    progress=100,
                    phase="The app restarted before this job finished. Run it again.",
                    completed_at=completed_at,
                    error="This job was interrupted by an app restart.",
                )
                recovered.append(dict(job))
        return recovered


def test_background_jobs_reuse_active_dedupe_key_and_report_progress():
    manager = BackgroundJobManager(max_workers=1)
    started = Event()
    release = Event()

    def task(context):
        context.update(35, "Working")
        started.set()
        assert release.wait(timeout=2)
        return {"ok": True, "message": "Finished"}

    first = manager.submit("test", task, dedupe_key="same")
    assert started.wait(timeout=2)
    second = manager.submit("test", task, dedupe_key="same")
    assert second["job_id"] == first["job_id"]
    assert second["reused"] is True
    assert manager.get(first["job_id"])["progress"] == 35
    release.set()
    manager._futures[first["job_id"]].result(timeout=2)
    completed = manager.get(first["job_id"])
    assert completed["status"] == "complete"
    assert completed["result"]["ok"] is True


def test_background_job_can_cancel_at_safe_checkpoint():
    manager = BackgroundJobManager(max_workers=1)
    started = Event()
    release = Event()

    def task(context):
        started.set()
        assert release.wait(timeout=2)
        context.update(50, "Checkpoint")
        return {"ok": True}

    job = manager.submit("cancel", task)
    assert started.wait(timeout=2)
    manager.cancel(job["job_id"])
    release.set()
    manager._futures[job["job_id"]].result(timeout=2)
    assert manager.get(job["job_id"])["status"] == "canceled"


def test_background_job_history_survives_manager_restart():
    repository = MemoryJobRepository()
    manager = BackgroundJobManager(max_workers=1, repository=repository)
    job = manager.submit("durable", lambda context: {"ok": True, "message": "Stored"})
    manager._futures[job["job_id"]].result(timeout=2)

    restarted = BackgroundJobManager(max_workers=1, repository=repository)
    restored = restarted.get(job["job_id"])

    assert restored["status"] == "complete"
    assert restored["result"] == {"ok": True, "message": "Stored"}


def test_background_job_restart_marks_active_work_interrupted():
    repository = MemoryJobRepository([{
        "job_id": "refresh-1",
        "kind": "refresh",
        "label": "Refresh",
        "dedupe_key": "refresh",
        "status": "running",
        "progress": 45,
        "phase": "Refreshing",
        "created_at": "2026-08-29T00:00:00+00:00",
        "started_at": "2026-08-29T00:00:01+00:00",
        "completed_at": "",
        "cancel_requested": False,
        "result": {},
        "error": "",
    }])

    manager = BackgroundJobManager(max_workers=1, repository=repository)
    restored = manager.get("refresh-1")

    assert restored["status"] == "failed"
    assert "restarted" in restored["phase"]


def test_background_job_deduplicates_across_managers():
    repository = MemoryJobRepository()
    first_manager = BackgroundJobManager(max_workers=1, repository=repository)
    started = Event()
    release = Event()

    def task(context):
        started.set()
        assert release.wait(timeout=2)
        return {"message": "Finished"}

    first = first_manager.submit("refresh", task, dedupe_key="shared-refresh")
    assert started.wait(timeout=2)
    second_manager = BackgroundJobManager(max_workers=1, repository=repository)
    second = second_manager.submit("refresh", task, dedupe_key="shared-refresh")

    assert second["job_id"] == first["job_id"]
    assert second["external"] is True
    release.set()
    first_manager._futures[first["job_id"]].result(timeout=2)
