"""Village search (Blueprint §03 `/villages` GET) — typeahead over real
village names, each result carrying taluka + district so an officer can
disambiguate two villages that share a name (Blueprint §05 — a real
occurrence in Latur district, not a hypothetical edge case; see
docs/DECISIONS.md, M2A P1). Auth-required like every other endpoint in
this API; there is no anonymous surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from geoalchemy2.functions import ST_Centroid, ST_X, ST_Y
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.admin import AdminBoundary
from app.models.enums import BoundaryLevel
from app.models.user import AppUser
from app.schemas.village import VillageCentroid, VillageSearchResult

router = APIRouter(prefix="/villages", tags=["Villages"])

# A short cap, not a page size — this backs a typeahead dropdown, not a
# browsable list; an officer refines the query rather than scrolling.
_MAX_RESULTS = 10
_MIN_QUERY_LENGTH = 2


@router.get("", response_model=list[VillageSearchResult])
async def search_villages(
    q: str,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VillageSearchResult]:
    query = q.strip()
    if len(query) < _MIN_QUERY_LENGTH:
        return []

    taluka = aliased(AdminBoundary)
    district = aliased(AdminBoundary)

    stmt = (
        select(
            AdminBoundary.id,
            AdminBoundary.name,
            taluka.name.label("taluka_name"),
            district.name.label("district_name"),
            ST_Y(ST_Centroid(AdminBoundary.geometry)).label("lat"),
            ST_X(ST_Centroid(AdminBoundary.geometry)).label("lon"),
        )
        .join(taluka, AdminBoundary.parent_id == taluka.id)
        .join(district, taluka.parent_id == district.id)
        .where(AdminBoundary.level == BoundaryLevel.VILLAGE, AdminBoundary.name.ilike(f"%{query}%"))
        .order_by(AdminBoundary.name)
        .limit(_MAX_RESULTS)
    )
    rows = (await db.execute(stmt)).all()

    return [
        VillageSearchResult(
            id=row.id,
            name=row.name,
            taluka=row.taluka_name,
            district=row.district_name,
            centroid=VillageCentroid(lat=row.lat, lon=row.lon),
        )
        for row in rows
    ]
