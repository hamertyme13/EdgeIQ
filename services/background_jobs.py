from __future__ import annotations

import copy
import logging
import os
import threading
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime

from repository.repositories.background_job_repository import BackgroundJobRepository

_log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobCancelled(RuntimeError):
    pass


class JobContext:
    def __init__(self, manager: BackgroundJobManager, job_id: str) -> None:
        self._manager = manager
        self.job_id = job_id

    def update(self, progress: int, phase: str) -> None:
        self._manager._update(self.job_id, progress=progress, phase=phase)
        if self.cancelled:
            raise JobCancelled("The job was canceled.")

    @property
    def cancelled(self) -> bool:
        return self._manager._cancel_requested(self.job_id)


JobCallable = Callable[[JobContext], dict]


class BackgroundJobManager:
    """Bounded in-process worker pool with deduplication and observable jobs."""

    def __init__(self, *, max_workers: int = 3, history_limit: int = 100, repository=None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="edgeiq-job")
        self._history_limit = max(20, history_limit)
        self._repository = repository
        self._owner_id = uuid.uuid4().hex
        self._process_id = os.getpid()
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._futures: dict[str, Future] = {}
        self._order: deque[str] = deque()
        self._active_keys: dict[str, str] = {}
        self._persisted_progress: dict[str, int] = {}
        self._load_persisted()

    def submit(self, kind: str, task: JobCallable, *, dedupe_key: str = "", label: str = "") -> dict:
        key = dedupe_key or kind
        with self._lock:
            existing_id = self._active_keys.get(key)
            if existing_id:
                existing = self._jobs.get(existing_id)
                if existing and existing["status"] in {"queued", "running", "canceling"}:
                    return {**self._public_job(existing), "reused": True}
            if self._repository is not None:
                try:
                    external = self._repository.active(key)
                except Exception:
                    _log.exception("Background-job deduplication lookup failed")
                    external = None
                if external:
                    self._remember_external_locked(external)
                    return {**self._public_job(external), "reused": True, "external": True}
            job_id = f"{kind}-{uuid.uuid4().hex[:12]}"
            job = {
                "job_id": job_id,
                "kind": kind,
                "label": label or kind.replace("_", " ").title(),
                "dedupe_key": key,
                "status": "queued",
                "progress": 0,
                "phase": "Waiting for an EdgeIQ worker.",
                "created_at": _now(),
                "started_at": "",
                "completed_at": "",
                "cancel_requested": False,
                "result": {},
                "error": "",
                "_owner_id": self._owner_id,
                "_process_id": self._process_id,
                "_heartbeat_at": _now(),
            }
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._active_keys[key] = job_id
            self._prune_locked()
            self._persist_locked(job_id, force=True)
            self._futures[job_id] = self._executor.submit(self._run, job_id, task)
            return self._public_job(job)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.get("_owner_id") != self._owner_id and self._repository is not None:
                job = self._repository.get(job_id) or job
                self._remember_external_locked(job)
            return self._public_job(job) if job else None

    def list(self, *, limit: int = 20) -> list[dict]:
        with self._lock:
            if self._repository is not None:
                try:
                    for persisted in self._repository.recent(max(limit, 20)):
                        local = self._jobs.get(persisted["job_id"])
                        if local is None or local.get("_owner_id") != self._owner_id:
                            self._remember_external_locked(persisted)
                except Exception:
                    _log.exception("Background-job history refresh failed")
            ids = list(self._order)[-max(1, min(limit, 100)):]
            return [self._public_job(self._jobs[job_id]) for job_id in reversed(ids) if job_id in self._jobs]

    def cancel(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job["status"] not in {"queued", "running"}:
                return self._public_job(job)
            if job.get("_owner_id") != self._owner_id:
                return self._public_job(job)
            job["cancel_requested"] = True
            job["status"] = "canceling"
            job["phase"] = "Cancel requested. EdgeIQ will stop at the next safe checkpoint."
            future = self._futures.get(job_id)
            if future is not None and future.cancel():
                self._finish_locked(job_id, status="canceled", phase="Canceled before the job started.")
            else:
                self._persist_locked(job_id, force=True)
            return self._public_job(job)

    def _run(self, job_id: str, task: JobCallable) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job["cancel_requested"]:
                self._finish_locked(job_id, status="canceled", phase="Canceled before the job started.")
                return
            job.update(status="running", progress=1, phase="Starting...", started_at=_now())
            self._persist_locked(job_id, force=True)
        try:
            result = task(JobContext(self, job_id)) or {}
            with self._lock:
                if self._jobs[job_id]["cancel_requested"]:
                    self._finish_locked(job_id, status="canceled", phase="Canceled.")
                else:
                    self._finish_locked(
                        job_id,
                        status="complete",
                        phase=str(result.get("message") or "Job complete."),
                        result=result,
                    )
        except JobCancelled:
            with self._lock:
                self._finish_locked(job_id, status="canceled", phase="Canceled.")
        except Exception as exc:
            _log.exception("Background job %s failed", job_id)
            with self._lock:
                self._finish_locked(
                    job_id,
                    status="failed",
                    phase="The job could not finish.",
                    error=str(exc) or "Unexpected background-job failure.",
                )

    def _update(self, job_id: str, *, progress: int, phase: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job["status"] not in {"canceling", "canceled"}:
                job["status"] = "running"
            job["progress"] = max(int(job["progress"]), min(99, max(0, int(progress))))
            job["phase"] = phase
            job["_heartbeat_at"] = _now()
            self._persist_locked(job_id)

    def _cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            return bool(self._jobs.get(job_id, {}).get("cancel_requested"))

    def _finish_locked(
        self,
        job_id: str,
        *,
        status: str,
        phase: str,
        result: dict | None = None,
        error: str = "",
    ) -> None:
        job = self._jobs[job_id]
        job.update(
            status=status,
            progress=100,
            phase=phase,
            completed_at=_now(),
            result=result or {},
            error=error,
            _heartbeat_at=_now(),
        )
        if self._active_keys.get(job["dedupe_key"]) == job_id:
            self._active_keys.pop(job["dedupe_key"], None)
        self._persist_locked(job_id, force=True)

    def _prune_locked(self) -> None:
        while len(self._order) > self._history_limit:
            job_id = self._order[0]
            job = self._jobs.get(job_id)
            if job and job["status"] in {"queued", "running", "canceling"}:
                break
            self._order.popleft()
            self._jobs.pop(job_id, None)
            self._futures.pop(job_id, None)
            self._persisted_progress.pop(job_id, None)

    def _load_persisted(self) -> None:
        if self._repository is None:
            return
        try:
            self._repository.recover_interrupted(_now())
            for job in self._repository.recent(self._history_limit):
                job_id = job["job_id"]
                self._jobs[job_id] = job
                self._order.append(job_id)
                self._persisted_progress[job_id] = int(job.get("progress") or 0)
        except Exception:
            _log.exception("Background-job history could not be loaded")

    def _persist_locked(self, job_id: str, *, force: bool = False) -> None:
        if self._repository is None:
            return
        job = self._jobs[job_id]
        progress = int(job.get("progress") or 0)
        previous = self._persisted_progress.get(job_id, -5)
        if not force and progress - previous < 5:
            return
        try:
            self._repository.save(copy.deepcopy(job))
            self._persisted_progress[job_id] = progress
        except Exception:
            _log.exception("Background job %s could not be persisted", job_id)

    def _remember_external_locked(self, job: dict) -> None:
        job_id = job["job_id"]
        self._jobs[job_id] = dict(job)
        if job_id not in self._order:
            self._order.append(job_id)

    @staticmethod
    def _public_job(job: dict) -> dict:
        return {key: copy.deepcopy(value) for key, value in job.items() if not key.startswith("_")}


background_jobs = BackgroundJobManager(repository=BackgroundJobRepository)
