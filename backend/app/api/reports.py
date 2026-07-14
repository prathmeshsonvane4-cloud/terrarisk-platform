"""Report generation trigger + fetch endpoints — the final two steps of
the Service 1 workflow (Blueprint §01):

    Create Farm -> Trigger Report -> Background Job -> Satellite
    Processing -> Risk Engine -> Persist Results -> Return Report JSON

`trigger_report` only ever schedules work and returns immediately (202);
`get_report` reads back whatever generate_farm_report() already persisted.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from geoalchemy2.functions import ST_AsGeoJSON
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user, owned_or_branch_filter, require_role, user_can_access_owned_resource
from app.core.config import get_settings
from app.database.session import get_db
from app.models.admin import AdminBoundary
from app.models.enums import JobStatus, JobType, RiskEntityType, SatelliteIndexType, UserRole
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.risk import ConfigWeight, RiskFactorScore, RiskScore
from app.models.satellite import SatelliteObservation
from app.models.user import AppUser
from app.schemas.report import (
    FactorScoreResponse,
    ObservationPoint,
    ReportEvidenceContext,
    ReportFarmContext,
    ReportGenerateRequest,
    ReportMethodContext,
    ReportResponse,
    ReportSeries,
    ReportTriggerResponse,
)
from app.schemas.workspace import ReportListItem, ReportListResponse
from app.services.reporting.map_snapshot import fetch_map_snapshot
from app.services.reporting.pdf_renderer import PDF_LAYOUT_VERSION, render_report_pdf
from app.services.reporting.report_generator import generate_farm_report
from app.services.risk.engine import RiskEngine
from app.services.satellite.gee_provider import GeeProvider, _monthly_periods

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
    in_flight_job = in_flight.scalar_one_or_none()
    if in_flight_job is not None:
        # job_id travels alongside the message (M2B P7 B5 — Product Design
        # v2 §7.2) so the UI can route straight to the existing run instead
        # of just reporting failure to start a new one.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "A report is already being generated for this farm",
                "job_id": str(in_flight_job.id),
            },
        )

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


async def _load_report_response(
    risk_score_id: UUID, current_user: AppUser, db: AsyncSession
) -> ReportResponse:
    """Shared payload assembly for the JSON and PDF endpoints — one loader,
    one authorization guard, so the two views can never diverge on either
    data or access rules (Blueprint §08 one-artifact rule)."""
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

    # M2A P5 enrichment — everything below is already-persisted data
    # (admin hierarchy, officer of record, the drawn geometry, and the
    # satellite_observation cache written during generation). No
    # recomputation, no live GEE call, per Blueprint §03.
    taluka = aliased(AdminBoundary)
    district = aliased(AdminBoundary)
    context_row = (
        await db.execute(
            select(
                AdminBoundary.name.label("village_name"),
                taluka.name.label("taluka_name"),
                district.name.label("district_name"),
                ST_AsGeoJSON(FarmPolygon.geometry).label("geometry_json"),
            )
            .select_from(FarmPolygon)
            .join(AdminBoundary, FarmPolygon.village_id == AdminBoundary.id)
            .join(taluka, AdminBoundary.parent_id == taluka.id)
            .join(district, taluka.parent_id == district.id)
            .where(FarmPolygon.id == farm.id)
        )
    ).one()
    officer = await db.get(AppUser, farm.drawn_by)
    config_weight = await db.get(ConfigWeight, risk_score.weights_version_id)

    observation_rows = (
        await db.execute(
            select(SatelliteObservation)
            .where(
                SatelliteObservation.entity_type == RiskEntityType.FARM,
                SatelliteObservation.entity_id == farm.id,
            )
            .order_by(SatelliteObservation.period_start)
        )
    ).scalars().all()
    series_by_type: dict[SatelliteIndexType, list[ObservationPoint]] = {
        SatelliteIndexType.NDVI: [],
        SatelliteIndexType.MNDWI: [],
        SatelliteIndexType.NDMI: [],
        SatelliteIndexType.RAINFALL: [],
    }
    for observation in observation_rows:
        bucket = series_by_type.get(observation.index_type)
        if bucket is not None:
            bucket.append(
                ObservationPoint(
                    period_start=observation.period_start,
                    value=observation.value,
                    source_dates=observation.source_dates,
                )
            )

    # M2B P9 — expected_months reuses the pipeline's OWN period-generation
    # helper against the persisted window, so it can never drift from what
    # that report actually expected to observe (Blueprint §03: no
    # recomputation of anything the engine already decided).
    expected_months = (
        len(_monthly_periods(risk_score.observation_window_start, risk_score.observation_window_end))
        if risk_score.observation_window_start and risk_score.observation_window_end
        else None
    )

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
        farm=ReportFarmContext(
            geometry=json.loads(context_row.geometry_json),
            village_name=context_row.village_name,
            taluka_name=context_row.taluka_name,
            district_name=context_row.district_name,
            officer_name=officer.full_name if officer else "Unknown officer",
        ),
        series=ReportSeries(
            ndvi=series_by_type[SatelliteIndexType.NDVI],
            mndwi=series_by_type[SatelliteIndexType.MNDWI],
            ndmi=series_by_type[SatelliteIndexType.NDMI],
            rainfall=series_by_type[SatelliteIndexType.RAINFALL],
        ),
        evidence=ReportEvidenceContext(
            observation_window_start=risk_score.observation_window_start,
            observation_window_end=risk_score.observation_window_end,
            expected_months=expected_months,
        ),
        method=ReportMethodContext(
            weights_version_id=risk_score.weights_version_id,
            weights=config_weight.weights if config_weight else {},
            weights_effective_from=config_weight.effective_from if config_weight else risk_score.computed_at,
            floor_threshold=(
                float(config_weight.floor_thresholds["threshold"]) if config_weight else 0.0
            ),
            weighted_average_score=risk_score.weighted_average_score,
        ),
    )


@router.get("/reports/{risk_score_id}", response_model=ReportResponse)
async def get_report(
    risk_score_id: UUID,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    return await _load_report_response(risk_score_id, current_user, db)


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportListResponse:
    """The Reports workspace index (M2B P7 — Product Design v2 §7, screen
    9): every issued report the caller owns or shares a branch with,
    newest first — the auditor/manager entry point ("show me every report
    issued," not "show me every farm"). One joined query; RiskScore is
    append-only so this is simply every farm-scored row in scope, no
    latest-per-farm collapsing (that collapsing is what the Farms index is
    for — this index is intentionally the full issued-artifact ledger)."""
    taluka = aliased(AdminBoundary)
    district = aliased(AdminBoundary)
    officer = aliased(AppUser)

    rows = (
        await db.execute(
            select(RiskScore, FarmPolygon, AdminBoundary.name, taluka.name, district.name, officer.full_name)
            .join(FarmPolygon, RiskScore.entity_id == FarmPolygon.id)
            .join(AdminBoundary, FarmPolygon.village_id == AdminBoundary.id)
            .join(taluka, AdminBoundary.parent_id == taluka.id)
            .join(district, taluka.parent_id == district.id)
            .join(officer, FarmPolygon.drawn_by == officer.id)
            .where(RiskScore.entity_type == RiskEntityType.FARM, owned_or_branch_filter(current_user, officer))
            .order_by(RiskScore.computed_at.desc())
        )
    ).all()

    items = [
        ReportListItem(
            risk_score_id=score.id,
            farm_id=farm.id,
            village_name=village_name,
            taluka_name=taluka_name,
            district_name=district_name,
            area_ha=farm.area_ha,
            officer_name=officer_name,
            overall_score=score.overall_score,
            overall_band=score.overall_band,
            confidence=score.confidence,
            computed_at=score.computed_at,
            model_version=score.model_version,
        )
        for score, farm, village_name, taluka_name, district_name, officer_name in rows
    ]
    return ReportListResponse(items=items, total=len(items))


def _render_pdf_blocking(report: ReportResponse) -> bytes:
    """Tile fetch + matplotlib + reportlab are all blocking; bundled here
    so the endpoint can push the whole render off the event loop."""
    map_png = fetch_map_snapshot(report.farm.geometry)
    return render_report_pdf(report, map_png)


@router.get("/reports/{risk_score_id}/pdf")
async def get_report_pdf(
    risk_score_id: UUID,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Blueprint §API: rendered PDF, cached after first render. A risk
    score row is immutable once computed, so the cache is keyed on
    (risk_score_id, layout version) and never expires — a layout change
    bumps PDF_LAYOUT_VERSION rather than invalidating files."""
    report = await _load_report_response(risk_score_id, current_user, db)

    cache_dir = Path(get_settings().report_pdf_cache_dir)
    cache_path = cache_dir / f"{report.id}-v{PDF_LAYOUT_VERSION}.pdf"
    if cache_path.is_file():
        pdf_bytes = cache_path.read_bytes()
    else:
        pdf_bytes = await asyncio.to_thread(_render_pdf_blocking, report)
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Atomic publish: a concurrent request must never read a half-written
        # file, so write to a unique temp name and os.replace into place.
        temp_path = cache_path.with_name(f"{cache_path.name}.{uuid4().hex}.tmp")
        temp_path.write_bytes(pdf_bytes)
        temp_path.replace(cache_path)

    village_slug = re.sub(r"[^A-Za-z0-9]+", "-", report.farm.village_name).strip("-") or "farm"
    filename = f"TerraRisk-Report-{village_slug}-{report.computed_at:%Y%m%d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
