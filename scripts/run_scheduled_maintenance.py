from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repository.database import initialize_database
from services.background_jobs import background_jobs
from web.app import _run_due_daily_operations


def wait_for_queued_jobs(result: dict, *, get_job=background_jobs.get, pause=time.sleep) -> list[dict]:
    completed = []
    for queued in result.get("jobs") or []:
        if queued.get("reused"):
            continue
        job_id = queued["job_id"]
        while True:
            job = get_job(job_id)
            if job and job.get("status") in {"complete", "failed", "canceled"}:
                completed.append({"job": queued["job"], "status": job["status"], "error": job.get("error") or ""})
                break
            pause(0.25)
    return completed


def main() -> int:
    if "--worker" not in sys.argv:
        timeout = max(60, int(os.getenv("EDGEIQ_MAINTENANCE_TIMEOUT_SECONDS", "180")))
        try:
            worker = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker"],
                cwd=ROOT, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            print(json.dumps({"ok": False, "message": "Scheduled maintenance exceeded its time limit. EdgeIQ will retry outstanding jobs."}), flush=True)
            return 1
        return worker.returncode
    initialize_database()
    result = _run_due_daily_operations()
    result["completed_jobs"] = wait_for_queued_jobs(result)
    result["ok"] = bool(result.get("ok", True)) and all(
        job["status"] == "complete" for job in result["completed_jobs"]
    )
    print(json.dumps(result, default=str), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
