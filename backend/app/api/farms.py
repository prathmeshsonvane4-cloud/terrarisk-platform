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

from app.api.deps import get_current_user, require_role
from app.database.session import get_db
from app.models.admin import AdminBoundary
from app.models.enums import BoundaryLevel, UserRole
from app.models.farm import FarmPolygon
from app.models.user import AppUser
from app.schemas.farm import FarmCreateRequest, FarmResponse

router = APIRouter(prefix="/farms", tags=["Farms"])

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
    if farm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Farm not found")
    return FarmResponse.model_validate(farm)
