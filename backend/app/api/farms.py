"""Farm polygon endpoints (Blueprint §01 Service 1 workflow, step 1-2).

Every write is role-gated (Credit Officer / Branch Manager), the drawing
officer's identity always comes from the authenticated JWT — never from
the request body — and the authoritative area is always computed
server-side via PostGIS, never trusted from the client (Blueprint §05).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_Area
from geoalchemy2.shape import from_shape
from sqlalchemy import cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user, owned_or_branch_filter, require_role, user_can_access_owned_resource
from app.database.session import get_db
from app.models.admin import AdminBoundary
from app.models.enums import BoundaryLevel, JobStatus, JobType, RiskEntityType, UserRole
from app.models.farm import FarmPolygon
from app.models.job import Job
from app.models.risk import RiskScore
from app.models.user import AppUser
from app.schemas.farm import FarmCreateRequest, FarmResponse
from app.schemas.workspace import (
    ActiveJobSummary,
    AssessmentSummary,
    FarmAssessmentHistoryResponse,
    FarmListItem,
    FarmListResponse,
)

router = APIRouter(prefix="/farms", tags=["Farms"])

_IN_FLIGHT_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)

# Defensive bounds against fat-fingered or catastrophically wrong polygons
# (e.g. an officer accidentally tracing a whole taluka instead of one
# field) — not a claim about typical smallholder farm size.
_MIN_FARM_AREA_HA = 0.01
_MAX_FARM_AREA_HA = 1000.0


@router.post("", response_model=FarmResponse, status_code=status.HTTP_201_CREATED)
async def create_farm(
    payload: FarmCreateRequest,
    current_user: AppUser = Depends(require_role(UserRole.CREDIT_OFFICER, UserRole.BRANCH_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> FarmResponse:
    """Persist an officer-drawn farm boundary. Geometry validity,
    closedness, coordinate range, and non-zero area are already enforced
    by FarmCreateRequest at the request-parsing boundary (app/schemas/farm.py)."""
    village = await db.get(AdminBoundary, payload.village_id)
    if village is None or village.level != BoundaryLevel.VILLAGE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="village_id does not reference a known village"
        )

    farm = FarmPolygon(
        village_id=payload.village_id,
        geometry=from_shape(payload.geometry.to_shapely(), srid=4326),
        area_ha=0,  # placeholder — overwritten below with the authoritative server-side value
        drawn_by=current_user.id,
    )
    db.add(farm)
    await db.flush()

    area_m2 = await db.scalar(select(ST_Area(cast(farm.geometry, Geography))))
    area_ha = area_m2 / 10_000

    if not (_MIN_FARM_AREA_HA <= area_ha <= _MAX_FARM_AREA_HA):
        await db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Computed area ({area_ha:.4f} ha) is outside the plausible range for a single farm",
        )

    farm.area_ha = area_ha
    await db.commit()
    await db.refresh(farm)
    return FarmResponse.model_validate(farm)


@router.get("/{farm_id}", response_model=FarmResponse)
async def get_farm(
    farm_id: UUID,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FarmResponse:
    farm = await db.get(FarmPolygon, farm_id)
    if farm is None or not await user_can_access_owned_resource(db, current_user, farm.drawn_by):
        # Same not-found-vs-forbidden guard as jobs/reports (app/api/deps.py) —
        # a farm that exists but belongs to another branch must be
        # indistinguishable from one that doesn't exist at all.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Farm not found")
    return FarmResponse.model_validate(farm)


@router.get("", response_model=FarmListResponse)
async def list_farms(
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FarmListResponse:
    """The Farms workspace index (M2B P7 — Product Design v2 §7, screen 7):
    every farm the caller owns or shares a branch with, each carrying its
    latest assessment (if any) and its currently in-flight run (if any) so
    the list alone answers "what's the state of every farm I map." Two
    small batch queries instead of a join, matching this codebase's
    existing style (no window functions) and MVP-pilot data volume."""
    taluka = aliased(AdminBoundary)
    district = aliased(AdminBoundary)
    officer = aliased(AppUser)

    farm_rows = (
        await db.execute(
            select(FarmPolygon, AdminBoundary.name, taluka.name, district.name, officer.full_name)
            .join(AdminBoundary, FarmPolygon.village_id == AdminBoundary.id)
            .join(taluka, AdminBoundary.parent_id == taluka.id)
            .join(district, taluka.parent_id == district.id)
            .join(officer, FarmPolygon.drawn_by == officer.id)
            .where(owned_or_branch_filter(current_user, officer))
            .order_by(FarmPolygon.created_at.desc())
        )
    ).all()
    farm_ids = [row[0].id for row in farm_rows]

    latest_by_farm: dict[UUID, RiskScore] = {}
    if farm_ids:
        score_rows = (
            await db.execute(
                select(RiskScore)
                .where(RiskScore.entity_type == RiskEntityType.FARM, RiskScore.entity_id.in_(farm_ids))
                .order_by(RiskScore.computed_at.desc())
            )
        ).scalars().all()
        for score in score_rows:
            latest_by_farm.setdefault(score.entity_id, score)  # first seen per farm = latest, desc order

    active_job_by_farm: dict[UUID, Job] = {}
    if farm_ids:
        job_rows = (
            await db.execute(
                select(Job)
                .where(
                    Job.type == JobType.FARM_REPORT,
                    Job.status.in_(_IN_FLIGHT_STATUSES),
                    Job.entity_id.in_(farm_ids),
                )
                .order_by(Job.created_at.desc())
            )
        ).scalars().all()
        for job in job_rows:
            active_job_by_farm.setdefault(job.entity_id, job)

    items = [
        FarmListItem(
            id=farm.id,
            village_id=farm.village_id,
            village_name=village_name,
            taluka_name=taluka_name,
            district_name=district_name,
            area_ha=farm.area_ha,
            officer_name=officer_name,
            drawn_by=farm.drawn_by,
            created_at=farm.created_at,
            latest_assessment=(
                AssessmentSummary(
                    risk_score_id=score.id,
                    overall_score=score.overall_score,
                    overall_band=score.overall_band,
                    confidence=score.confidence,
                    computed_at=score.computed_at,
                    model_version=score.model_version,
                )
                if (score := latest_by_farm.get(farm.id))
                else None
            ),
            active_job=(
                ActiveJobSummary(job_id=job.id, status=job.status, created_at=job.created_at)
                if (job := active_job_by_farm.get(farm.id))
                else None
            ),
        )
        for farm, village_name, taluka_name, district_name, officer_name in farm_rows
    ]
    return FarmListResponse(items=items, total=len(items))


@router.get("/{farm_id}/assessments", response_model=FarmAssessmentHistoryResponse)
async def get_farm_assessment_history(
    farm_id: UUID,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FarmAssessmentHistoryResponse:
    """Every completed assessment for this farm, newest first, plus the
    in-flight run if any — the Farm detail timeline (Product Design v2
    §7.4). Same append-only RiskScore history the risk engine already
    guarantees (Blueprint §04/§07); this endpoint is a read-model over it,
    nothing new persisted."""
    farm = await db.get(FarmPolygon, farm_id)
    if farm is None or not await user_can_access_owned_resource(db, current_user, farm.drawn_by):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Farm not found")

    score_rows = (
        await db.execute(
            select(RiskScore)
            .where(RiskScore.entity_type == RiskEntityType.FARM, RiskScore.entity_id == farm_id)
            .order_by(RiskScore.computed_at.desc())
        )
    ).scalars().all()

    active_job = (
        await db.execute(
            select(Job)
            .where(
                Job.type == JobType.FARM_REPORT,
                Job.status.in_(_IN_FLIGHT_STATUSES),
                Job.entity_id == farm_id,
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return FarmAssessmentHistoryResponse(
        farm_id=farm_id,
        items=[
            AssessmentSummary(
                risk_score_id=score.id,
                overall_score=score.overall_score,
                overall_band=score.overall_band,
                confidence=score.confidence,
                computed_at=score.computed_at,
                model_version=score.model_version,
            )
            for score in score_rows
        ],
        active_job=(
            ActiveJobSummary(job_id=active_job.id, status=active_job.status, created_at=active_job.created_at)
            if active_job
            else None
        ),
    )
