from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import BoundaryLevel


class AdminBoundarySummary(BaseModel):
    """One row in a cascading dropdown — deliberately minimal by default.

    `geometry` stays `None` unless the caller explicitly asks for it with
    `?include_geometry=true`, so the dropdown case this schema was built
    for is byte-for-byte unchanged. The opt-in exists because drawing a
    village's neighbours is otherwise impossible without one request per
    neighbour: the per-id detail endpoint is the only other source of
    geometry, and a taluka like Devadurga has 185 villages. One request
    returning ~120 kB of simplified geometry replaces 185 round trips.
    """

    id: UUID
    level: BoundaryLevel
    name: str
    lgd_code: str | None
    geometry: dict[str, Any] | None = None


class AdminBoundaryDetail(BaseModel):
    """Full detail for the Select Area preview/confirm step: the boundary's
    own geometry plus its resolved ancestor names at every level that
    applies (a taluka has no `village`; a village has all four).

    `parent_id` is a direct passthrough of the existing column, added so
    a caller that already has one boundary's detail (a village, say) can
    fetch its immediate parent's own geometry and children — its taluka
    outline, and that taluka's other villages — without a second
    name-based lookup walking the hierarchy from the top.
    """

    id: UUID
    level: BoundaryLevel
    name: str
    lgd_code: str | None
    parent_id: UUID | None
    state: str | None
    district: str | None
    taluka: str | None
    village: str | None
    geometry: dict[str, Any]
    area_ha: float
