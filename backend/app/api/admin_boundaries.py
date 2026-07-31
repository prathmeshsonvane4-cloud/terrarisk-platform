"""Admin-boundary hierarchy browsing for the Select Area workflow
(docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md Part 4).

Additive alongside villages.py's existing free-text search, which stays
exactly as it is and keeps serving Service 1's typeahead. This router
answers two different questions that no existing endpoint answers:
"what are the children of this boundary" (drives cascading
State -> District -> Taluka -> Village dropdowns off one generic
endpoint) and "what does this boundary look like" (name, resolved
ancestor chain, geometry, area — drives the zoom/highlight/confirm step
once a village is picked). Auth-required like every other endpoint in
this API.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_Area, ST_AsGeoJSON
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.admin import AdminBoundary
from app.models.enums import BoundaryLevel
from app.models.user import AppUser
from app.schemas.admin_boundary import AdminBoundaryDetail, AdminBoundarySummary

router = APIRouter(prefix="/admin-boundaries", tags=["Admin Boundaries"])

# Fixed by BoundaryLevel itself — used only as a hop cap when walking
# parent_id upward, so a corrupt/cyclic parent_id can never spin forever.
_MAX_HOPS = 4


@router.get("", response_model=list[AdminBoundarySummary])
async def list_admin_boundaries(
    parent_id: UUID | None = Query(default=None, description="Omit to list top-level states."),
    level: BoundaryLevel | None = Query(default=None, description="Optional extra filter; children are already one level below parent_id."),
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AdminBoundarySummary]:
    conditions = [AdminBoundary.parent_id == parent_id if parent_id is not None else AdminBoundary.parent_id.is_(None)]
    if level is not None:
        conditions.append(AdminBoundary.level == level)

    stmt = select(AdminBoundary).where(*conditions).order_by(AdminBoundary.name)
    rows = (await db.execute(stmt)).scalars().all()

    return [
        AdminBoundarySummary(id=row.id, level=row.level, name=row.name, lgd_code=row.lgd_code) for row in rows
    ]


@router.get("/{boundary_id}", response_model=AdminBoundaryDetail)
async def get_admin_boundary(
    boundary_id: UUID,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminBoundaryDetail:
    boundary = await db.get(AdminBoundary, boundary_id)
    if boundary is None:
        raise HTTPException(status_code=404, detail="Administrative boundary not found")

    # A catchment's admin_boundary_id may point at any level (village,
    # taluka, district, or even state — see Catchment's own schema
    # comment), so the ancestor walk can't assume a fixed depth the way
    # reports.py's village-only alias-join does.
    names_by_level: dict[BoundaryLevel, str] = {boundary.level: boundary.name}
    current = boundary
    for _ in range(_MAX_HOPS):
        if current.parent_id is None:
            break
        current = await db.get(AdminBoundary, current.parent_id)
        if current is None:
            break
        names_by_level[current.level] = current.name

    # Area is computed on the true geometry, matching catchments.py's own
    # ST_Area convention; the preview map renders geometry_simplified
    # (falling back to geometry for older rows with no simplified copy
    # computed yet), matching admin.py's own "simplified copy is what map
    # layers render" docstring.
    geometry_row = (
        await db.execute(
            select(
                ST_AsGeoJSON(func.coalesce(AdminBoundary.geometry_simplified, AdminBoundary.geometry)).label(
                    "geometry_json"
                ),
                ST_Area(cast(AdminBoundary.geometry, Geography)).label("area_m2"),
            ).where(AdminBoundary.id == boundary_id)
        )
    ).one()

    return AdminBoundaryDetail(
        id=boundary.id,
        level=boundary.level,
        name=boundary.name,
        lgd_code=boundary.lgd_code,
        state=names_by_level.get(BoundaryLevel.STATE),
        district=names_by_level.get(BoundaryLevel.DISTRICT),
        taluka=names_by_level.get(BoundaryLevel.TALUKA),
        village=names_by_level.get(BoundaryLevel.VILLAGE),
        geometry=json.loads(geometry_row.geometry_json),
        area_ha=geometry_row.area_m2 / 10_000,
    )
