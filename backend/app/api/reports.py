"""Report generation trigger + fetch endpoints — the final two steps of
the Service 1 workflow (Blueprint §01):

    Create Farm -> Trigger Report -> Background Job -> Satellite
    Processing -> Risk Engine -> Persist Results -> Return Report JSON

`trigger_report` only ever schedules work and returns immediately (202);
`get_report` reads back whatever generate_farm_report() already persisted.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role, user_can_access_owned_resource
from app.database.session import get_db
from app.models.enums import JobStatus, JobType, RiskEntityType, UserRole
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.risk import RiskFactorScore, RiskScore
from app.models.user import AppUser
from app.schemas.report import FactorScoreResponse, ReportGenerateRequest, ReportResponse, ReportTriggerResponse
from app.services.reporting.report_generator import generate_farm_report
from app.services.risk.engine import RiskEngine
from app.services.satellite.gee_provider import GeeProvider

router = APIRouter(tags=["Reports"])


async def _run_report_job(job_id: UUID, farm_id: UUID, lookback_years: int) -> None:
    """Background-task entry point. GeeProvider() is constructed here —
    lazily, only once this actually runs — never in the request handler:
    BackgroundTasks.add_task() evaluates its arguments immediately when
    scheduled, so passing a pre-built GeeProvider() to add_task() would
    trigger real Earth Engine authentication synchronously inside the
    request, blocking the officer and defeating the point of a background
    job entirely.

    Constructing it via asyncio.to_thread(), not directly: GeeProvider.
    __init__ calls ee.Initialize() on its first-ever use in this process,
    which is a blocking network call (the earthengine-api SDK has no async
    variant) — calling it directly here would still block this process's
    event loop for that first call, even though we're already inside a
    background task.
    """
    satellite_provider = await asyncio.to_thread(GeeProvider)
    await generate_farm_report(
        job_id=job_id,
        farm_id=farm_id,
        lookback_years=lookback_years,
        satellite_provider=satellite_provider,
        risk_engine=RiskEngine(),
    )


@router.post(
    "/farms/{farm_id}/reports", response_model=ReportTriggerResponse, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_report(
    farm_id: UUID,
    payload: ReportGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: AppUser = Depends(require_role(UserRole.CREDIT_OFFICER, UserRole.BRANCH_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ReportTriggerResponse:
    farm = await db.get(FarmPolygon, farm_id)
    if farm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Farm not found")

    # Transaction-scoped Postgres advisory lock, keyed on this farm — closes
    # a real TOCTOU race found in review: without it, two concurrent POSTs
    # for the same farm could both pass the "no job in flight" check below
    # before either commits, creating two simultaneous report jobs. The
    # lock serializes concurrent requests for the *same* farm only (a
    # different farm_id hashes to a different key and proceeds unblocked),
    # and releases automatically at commit/rollback — no schema change,
    # no new table, nothing to clean up.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('farm_report'), hashtext(:farm_id))"), {"farm_id": str(farm_id)})

    in_flight = await db.execute(
        select(Job).where(
            Job.type == JobType.FARM_REPORT,
            Job.entity_id == farm_id,
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
    )
    if in_flight.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A report is already being generated for this farm")

    # entity_id holds farm_id while the job is in flight (for the
    # in-progress check above); generate_farm_report() overwrites it with
    # the resulting risk_score.id once the job reaches DONE — the same
    # column serves both purposes since a completed job no longer needs
    # to advertise which farm it was for (the resulting RiskScore already
    # carries that).
    job = Job(type=JobType.FARM_REPORT, status=JobStatus.PENDING, entity_id=farm_id, created_by=current_user.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(
        _run_report_job, job_id=job.id, farm_id=farm_id, lookback_years=payload.lookback_years
    )

    return ReportTriggerResponse(job_id=job.id, status="queued")


@router.get("/reports/{risk_score_id}", response_model=ReportResponse)
async def get_report(
    risk_score_id: UUID,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    risk_score = await db.get(RiskScore, risk_score_id)
    if risk_score is None or risk_score.entity_type != RiskEntityType.FARM:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Report not found")

    farm = await db.get(FarmPolygon, risk_score.entity_id)
    if farm is None or not await user_can_access_owned_resource(db, current_user, farm.drawn_by):
        # Same not-found-vs-forbidden guard as jobs (app/api/jobs.py).
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Report not found")

    factor_rows = (
        await db.execute(select(RiskFactorScore).where(RiskFactorScore.risk_score_id == risk_score.id))
    ).scalars().all()

    return ReportResponse(
        id=risk_score.id,
        farm_id=farm.id,
        farm_area_ha=farm.area_ha,
        village_id=farm.village_id,
        overall_score=risk_score.overall_score,
        overall_band=risk_score.overall_band,
        confidence=risk_score.confidence,
        model_version=risk_score.model_version,
        computed_at=risk_score.computed_at,
        factors=[FactorScoreResponse.model_validate(f) for f in factor_rows],
    )
