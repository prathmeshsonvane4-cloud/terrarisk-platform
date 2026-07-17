"""Farm polygon request/response schemas, with validation enforced at the
request boundary (Blueprint §01/§05): malformed, self-intersecting,
zero-area, or out-of-range geometry is rejected before it ever reaches
application logic — never trusted from the client.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.validation import explain_validity

_MIN_LONGITUDE, _MAX_LONGITUDE = -180.0, 180.0
_MIN_LATITUDE, _MAX_LATITUDE = -90.0, 90.0

# RC1 audit finding: only a *minimum* ring length was enforced. A hand-drawn
# field boundary (Blueprint §01) realistically needs tens of vertices, never
# thousands — an unbounded ring lets a client submit an arbitrarily large
# coordinate array that Shapely, PostGIS ST_Area, and the geodesic preview
# all then have to process synchronously in the request path (not the
# background job), a cheap request-path DoS vector with no legitimate use.
# 2000 is generous headroom over any real hand-traced boundary.
_MAX_RING_POINTS = 2000

# RFC 7946 GeoJSON is WGS84-only and normally carries no CRS member at all;
# the older (deprecated) GeoJSON CRS member is accepted here only if it
# explicitly names WGS84 — anything else is rejected rather than silently
# misinterpreted, since every geometry column in this schema is SRID 4326
# (Blueprint §05).
_SUPPORTED_CRS_NAMES = {"EPSG:4326", "urn:ogc:def:crs:OGC::CRS84", "urn:ogc:def:crs:OGC:1.3:CRS84"}


class GeoJSONPolygon(BaseModel):
    """A single-ring GeoJSON Polygon (no holes, no MultiPolygon) — a
    hand-drawn farm boundary is expected to be one simple, contiguous
    shape (Blueprint §01: manual polygon drawing is the deliberate MVP
    approach)."""

    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]]
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
    def _validate_ring_structure(cls, value: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
        if len(value) != 1:
            raise ValueError("Only a single ring (no holes) is supported for a farm boundary")
        ring = value[0]
        if len(ring) < 4:
            raise ValueError("A polygon ring must have at least 4 points (3 unique + closing point)")
        if len(ring) > _MAX_RING_POINTS:
            raise ValueError(f"A polygon ring may have at most {_MAX_RING_POINTS} points ({len(ring)} given)")
        if ring[0] != ring[-1]:
            raise ValueError("Polygon ring is not closed — first and last coordinates must match")
        for longitude, latitude in ring:
            # Explicit finiteness check rather than relying on NaN/Infinity
            # happening to fail the chained range comparison below (they
            # currently do, but that's comparison-chaining trivia, not a
            # documented guarantee — worth being explicit).
            if not (math.isfinite(longitude) and math.isfinite(latitude)):
                raise ValueError(f"Coordinate ({longitude}, {latitude}) is not finite")
            if not (_MIN_LONGITUDE <= longitude <= _MAX_LONGITUDE):
                raise ValueError(f"Longitude {longitude} is out of valid range [-180, 180]")
            if not (_MIN_LATITUDE <= latitude <= _MAX_LATITUDE):
                raise ValueError(f"Latitude {latitude} is out of valid range [-90, 90]")
        return value

    @model_validator(mode="after")
    def _validate_simple_geometry(self) -> GeoJSONPolygon:
        try:
            polygon = ShapelyPolygon(self.coordinates[0])
        except Exception as exc:
            raise ValueError(f"Could not construct a polygon from the given coordinates: {exc}") from exc
        if not polygon.is_valid:
            raise ValueError(f"Polygon is not a valid simple geometry: {explain_validity(polygon)}")
        if polygon.area <= 0:
            raise ValueError("Polygon has zero area")
        return self

    def to_shapely(self) -> ShapelyPolygon:
        return ShapelyPolygon(self.coordinates[0])


class FarmCreateRequest(BaseModel):
    village_id: UUID
    geometry: GeoJSONPolygon


class FarmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    village_id: UUID
    area_ha: float
    drawn_by: UUID
    created_at: datetime
