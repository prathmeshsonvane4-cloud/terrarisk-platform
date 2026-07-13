"""Async job polling endpoint (Blueprint §03) — one uniform pattern shared
by both services: trigger returns a job_id, the client polls this
endpoint until the job reaches a terminal status."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user, owned_or_branch_filter, user_can_access_owned_resource
from app.database.session import get_db
from app.models.admin import AdminBoundary
from app.models.enums import JobStatus, JobType, RiskEntityType
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.risk import RiskScore
from app.models.user import AppUser
from app.schemas.job import JobStatusResponse
from app.schemas.workspace import AssessmentListItem, AssessmentListResponse

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


@router.get("", response_model=AssessmentListResponse)
async def list_assessments(
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssessmentListResponse:
    """The Assessments workspace index (M2B P7 — Product Design v2 §7,
    screen 5): every farm_report run the caller owns or shares a branch
    with, farm context resolved regardless of run status.

    `entity_id` is polymorphic by design (P4 decision, report_generator.py):
    while a job is in flight or failed it holds the farm_id it was
    triggered for; once DONE it is overwritten with the resulting
    risk_score_id. Listing "every assessment with its farm" therefore means
    resolving both shapes and merging them — no schema change, just reading
    what's already there two different ways.
    """
    creator = aliased(AppUser)
    job_rows = (
        await db.execute(
            select(Job, creator.full_name)
            .join(creator, Job.created_by == creator.id)
            .where(Job.type == JobType.FARM_REPORT, owned_or_branch_filter(current_user, creator))
            .order_by(Job.created_at.desc())
        )
    ).all()

    done_pairs: list[tuple[Job, str]] = []
    other_pairs: list[tuple[Job, str]] = []
    for job, name in job_rows:
        (done_pairs if job.status == JobStatus.DONE and job.entity_id is not None else other_pairs).append(
            (job, name)
        )

    scores_by_id: dict[UUID, RiskScore] = {}
    risk_score_ids = [job.entity_id for job, _ in done_pairs]
    if risk_score_ids:
        rows = (await db.execute(select(RiskScore).where(RiskScore.id.in_(risk_score_ids)))).scalars().all()
        scores_by_id = {score.id: score for score in rows}

    farm_ids: set[UUID] = set()
    for score in scores_by_id.values():
        if score.entity_type == RiskEntityType.FARM:
            farm_ids.add(score.entity_id)
    for job, _ in other_pairs:
        if job.entity_id is not None:
            farm_ids.add(job.entity_id)

    farms_by_id: dict[UUID, tuple[FarmPolygon, str]] = {}
    if farm_ids:
        rows = (
            await db.execute(
                select(FarmPolygon, AdminBoundary.name)
                .join(AdminBoundary, FarmPolygon.village_id == AdminBoundary.id)
                .where(FarmPolygon.id.in_(farm_ids))
            )
        ).all()
        farms_by_id = {farm.id: (farm, village_name) for farm, village_name in rows}

    items: list[AssessmentListItem] = []
    for job, officer_name in done_pairs:
        score = scores_by_id.get(job.entity_id)
        farm_id = score.entity_id if score and score.entity_type == RiskEntityType.FARM else None
        farm, village_name = farms_by_id.get(farm_id, (None, None)) if farm_id else (None, None)
        items.append(
            AssessmentListItem(
                job_id=job.id,
                status=job.status,
                created_at=job.created_at,
                updated_at=job.updated_at,
                farm_id=farm_id,
                village_name=village_name,
                area_ha=farm.area_ha if farm else None,
                officer_name=officer_name,
                risk_score_id=score.id if score else None,
                overall_score=score.overall_score if score else None,
                overall_band=score.overall_band if score else None,
                error_message=job.error_message,
            )
        )
    for job, officer_name in other_pairs:
        farm, village_name = farms_by_id.get(job.entity_id, (None, None)) if job.entity_id else (None, None)
        items.append(
            AssessmentListItem(
                job_id=job.id,
                status=job.status,
                created_at=job.created_at,
                updated_at=job.updated_at,
                farm_id=job.entity_id,
                village_name=village_name,
                area_ha=farm.area_ha if farm else None,
                officer_name=officer_name,
                risk_score_id=None,
                overall_score=None,
                overall_band=None,
                error_message=job.error_message,
            )
        )

    items.sort(key=lambda item: item.created_at, reverse=True)
    return AssessmentListResponse(items=items, total=len(items))
