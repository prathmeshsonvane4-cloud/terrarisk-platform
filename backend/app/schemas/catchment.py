"""Catchment request/response schemas (Water Intelligence, ticket M4-001),
with validation enforced at the request boundary — mirroring
`schemas/farm.py`'s exact discipline: malformed, self-intersecting, or
out-of-range geometry is rejected before it ever reaches application
logic, never trusted from the client.

`GeoJSONMultiPolygon` below is a deliberate near-clone of
`farm.py::GeoJSONPolygon`, not an import from it — the same "clone the
shape, don't create a cross-domain dependency between unrelated request
schemas" discipline this codebase already applies to its pure engines
(`WaterBalanceEngine`/`RechargeStressEngine` clone `RiskEngine`'s
statistical helpers rather than importing them).

Deliberately NOT validated here (out of this ticket's scope, per its own
"do not add business logic" instruction, and matching
`FarmCreateRequest`'s own exact precedent — that schema does not validate
farm area either):
- `area_ha` — server-recomputed via `ST_Area(geography cast)` at the API
  layer (a later ticket, mirroring `Catchment`'s own model docstring:
  "area_ha is always server-recomputed... exactly like
  FarmPolygon.area_ha"), never trusted from a client-supplied value, and
  never computable correctly from raw lon/lat degrees without a geodesic
  calculation this schema layer has no business performing.
- Whether a submitted `organization_id`/`admin_boundary_id` actually
  exists — a database lookup, out of scope for a pure request schema.

Vertex-count IS validated here (structural, not business logic) — the
same "cheap request-path DoS vector with no legitimate use" reasoning
`farm.py` already documents for its own ring-length cap, extended here to
match `Catchment`'s own `chk_catchment_vertex_count` CHECK constraint
bound exactly, so a client gets a fast, clear 422 instead of a database
error for the same violation.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.validation import explain_validity

from app.models.enums import DelineationMethod

_MIN_LONGITUDE, _MAX_LONGITUDE = -180.0, 180.0
_MIN_LATITUDE, _MAX_LATITUDE = -90.0, 90.0

# Matches Catchment's own chk_catchment_vertex_count CHECK constraint
# exactly (app/models/catchment.py: "ST_NPoints(geometry) <= 2000") — a
# structural request-payload-size guard, not a business-logic decision,
# so it belongs at the schema layer per farm.py's own precedent.
_MAX_TOTAL_VERTEX_COUNT = 2000

# RFC 7946 GeoJSON is WGS84-only; the deprecated GeoJSON CRS member is
# accepted only if it explicitly names WGS84 — identical policy to
# farm.py's GeoJSONPolygon, since every geometry column in this schema is
# SRID 4326 (Blueprint v2 Part 5).
_SUPPORTED_CRS_NAMES = {"EPSG:4326", "urn:ogc:def:crs:OGC::CRS84", "urn:ogc:def:crs:OGC:1.3:CRS84"}

_Ring = list[tuple[float, float]]
_PolygonRings = list[_Ring]
_MultiPolygonCoordinates = list[_PolygonRings]


def _validate_ring(ring: _Ring) -> None:
    if len(ring) < 4:
        raise ValueError("A polygon ring must have at least 4 points (3 unique + closing point)")
    if ring[0] != ring[-1]:
        raise ValueError("Polygon ring is not closed — first and last coordinates must match")
    for longitude, latitude in ring:
        if not (math.isfinite(longitude) and math.isfinite(latitude)):
            raise ValueError(f"Coordinate ({longitude}, {latitude}) is not finite")
        if not (_MIN_LONGITUDE <= longitude <= _MAX_LONGITUDE):
            raise ValueError(f"Longitude {longitude} is out of valid range [-180, 180]")
        if not (_MIN_LATITUDE <= latitude <= _MAX_LATITUDE):
            raise ValueError(f"Latitude {latitude} is out of valid range [-90, 90]")


class GeoJSONMultiPolygon(BaseModel):
    """A GeoJSON MultiPolygon — `Catchment.geometry`'s exact shape
    (`app/models/catchment.py`: MULTIPOLYGON, not POLYGON, "unlike a
    single farm field, a real watershed is not guaranteed to be simply
    connected"). A client submitting a single simply-connected boundary
    still uses this type, wrapped as a one-element MultiPolygon — valid,
    ordinary GeoJSON, not a special case this schema needs to detect.

    Unlike `farm.py::GeoJSONPolygon`, holes (rings after the first, per
    polygon) are structurally permitted — a real watershed excluding an
    enclosed area is physically meaningful in a way a single farm
    field's boundary is not, so no "single ring only" restriction is
    imposed here.
    """

    type: Literal["MultiPolygon"]
    coordinates: _MultiPolygonCoordinates
    crs: dict | None = None

    @field_validator("crs")
    @classmethod
    def _validate_crs(cls, value: dict | None) -> dict | None:
        if value is None:
            return value
        name = (value.get("properties") or {}).get("name", "")
        if name not in _SUPPORTED_CRS_NAMES:
            raise ValueError(f"Unsupported CRS '{name}' — only WGS84 (EPSG:4326) is supported")
        return value

    @field_validator("coordinates")
    @classmethod
    def _validate_structure(cls, value: _MultiPolygonCoordinates) -> _MultiPolygonCoordinates:
        if not value:
            raise ValueError("A MultiPolygon must contain at least one polygon")

        total_vertices = 0
        for polygon_index, polygon_rings in enumerate(value):
            if not polygon_rings:
                raise ValueError(f"Polygon {polygon_index} has no rings")
            for ring in polygon_rings:
                _validate_ring(ring)
                total_vertices += len(ring)

        if total_vertices > _MAX_TOTAL_VERTEX_COUNT:
            raise ValueError(
                f"MultiPolygon may have at most {_MAX_TOTAL_VERTEX_COUNT} total vertices "
                f"({total_vertices} given)"
            )
        return value

    @model_validator(mode="after")
    def _validate_simple_geometry(self) -> GeoJSONMultiPolygon:
        try:
            polygons = [ShapelyPolygon(rings[0], rings[1:]) for rings in self.coordinates]
            multipolygon = ShapelyMultiPolygon(polygons)
        except Exception as exc:
            raise ValueError(f"Could not construct a MultiPolygon from the given coordinates: {exc}") from exc
        if not multipolygon.is_valid:
            raise ValueError(f"MultiPolygon is not a valid geometry: {explain_validity(multipolygon)}")
        if multipolygon.area <= 0:
            raise ValueError("MultiPolygon has zero area")
        return self

    def to_shapely(self) -> ShapelyMultiPolygon:
        polygons = [ShapelyPolygon(rings[0], rings[1:]) for rings in self.coordinates]
        return ShapelyMultiPolygon(polygons)


class CatchmentCreateRequest(BaseModel):
    """`POST /catchments` request body (manual-draw path, a later
    ticket). `delineation_method` is deliberately NOT a client-supplied
    field on either request schema in this file — it is determined by
    which endpoint received the request (this one always means MANUAL;
    the upload endpoint always means UPLOAD), the same "one validation
    boundary, two ways in" design Blueprint v2 D2 already establishes,
    not a value the client should be trusted to assert.
    """

    name: str = Field(min_length=1, max_length=255)
    geometry: GeoJSONMultiPolygon
    organization_id: UUID | None = Field(
        default=None, description="Nullable in MVP — schema-ready for multi-tenancy, not yet enforced (Blueprint v2 D8)."
    )
    admin_boundary_id: UUID | None = Field(
        default=None, description="Optional link for village-level aggregation, not required for a catchment to exist on its own."
    )


class CatchmentUploadRequest(BaseModel):
    """Metadata accompanying `POST /catchments/upload` (a later ticket).
    The uploaded boundary file itself (GeoJSON/KML/zipped Shapefile) is
    handled by FastAPI's own multipart `UploadFile` mechanism at the
    route layer, not represented as a field on this JSON-body schema —
    this model covers only the metadata fields submitted alongside it.
    """

    name: str = Field(min_length=1, max_length=255)
    organization_id: UUID | None = None
    admin_boundary_id: UUID | None = None


class CatchmentResponse(BaseModel):
    """Mirrors `FarmResponse`'s exact convention: no raw geometry field
    in the basic response (geometry is fetched separately, e.g. for map
    rendering, by a later ticket's dedicated endpoint) — only scalar and
    list fields a client needs to display or reference a catchment by
    id.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    area_ha: float
    delineation_method: DelineationMethod
    organization_id: UUID | None
    admin_boundary_id: UUID | None
    resolution_flags: list[str] = Field(
        description='e.g. ["rainfall_sub_pixel", "et_sub_pixel", "high_relief_terrain"] — computed once at '
        "creation and reused by every downstream report (Blueprint v2 Part 4/Part 5)."
    )
    created_by: UUID
    created_at: datetime


class CatchmentDetailResponse(CatchmentResponse):
    """A single catchment, plus the geometry actually analysed.

    Deliberately a subclass used only by `GET /catchments/{id}` rather
    than a field added to `CatchmentResponse` itself: the list endpoint
    shares that model and is fetched wholesale by the map, the Priority
    Queue and the compare view, so putting geometry on it would attach a
    polygon to every row of every list for the sake of one detail screen.

    Exists so a report can draw the area it was actually computed over.
    Where an AOI was reshaped away from its village boundary, that shape
    lives only in `catchment.geometry` — the admin-boundary endpoints
    know nothing about it.
    """

    geometry: dict[str, Any]
