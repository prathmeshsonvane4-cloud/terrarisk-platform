"""Async job polling endpoint (Blueprint §03) — one uniform pattern shared
by both services: trigger returns a job_id, the client polls this
endpoint until the job reaches a terminal status."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, user_can_access_owned_resource
from app.database.session import get_db
from app.models.job import Job
from app.models.user import AppUser
from app.schemas.job import JobStatusResponse

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: UUID,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse:
    job = await db.get(Job, job_id)
    if job is None or not await user_can_access_owned_resource(db, current_user, job.created_by):
        # 404 either way — a job that exists but belongs to someone else
        # must be indistinguishable from one that doesn't exist at all,
        # to avoid leaking which job ids are valid to an unauthorized caller.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobStatusResponse.model_validate(job)
