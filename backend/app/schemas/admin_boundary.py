from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import BoundaryLevel


class AdminBoundarySummary(BaseModel):
    """One row in a cascading dropdown — deliberately minimal, no geometry."""

    id: UUID
    level: BoundaryLevel
    name: str
    lgd_code: str | None


class AdminBoundaryDetail(BaseModel):
    """Full detail for the Select Area preview/confirm step: the boundary's
    own geometry plus its resolved ancestor names at every level that
    applies (a taluka has no `village`; a village has all four)."""

    id: UUID
    level: BoundaryLevel
    name: str
    lgd_code: str | None
    state: str | None
    district: str | None
    taluka: str | None
    village: str | None
    geometry: dict[str, Any]
    area_ha: float
