from fastapi import APIRouter, HTTPException

from services.background_jobs import background_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(limit: int = 20) -> dict:
    return {"jobs": background_jobs.list(limit=limit)}


@router.get("/{job_id}")
def job_status(job_id: str) -> dict:
    job = background_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="That background job is no longer available.")
    return job


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = background_jobs.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="That background job is no longer available.")
    return job
