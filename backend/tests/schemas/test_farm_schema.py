"""Pure, offline tests for GeoJSON polygon validation — no database, no
network. Every one of these is a request the API must reject at the
parsing boundary, before it ever reaches application logic."""

import pytest
from pydantic import ValidationError

from app.schemas.farm import GeoJSONPolygon

_VALID_SQUARE = [[76.0, 18.0], [76.01, 18.0], [76.01, 18.01], [76.0, 18.01], [76.0, 18.0]]


def _polygon(coordinates=None, **overrides):
    payload = {"type": "Polygon", "coordinates": [coordinates or _VALID_SQUARE]}
    payload.update(overrides)
    return payload


def test_valid_simple_polygon_is_accepted():
    polygon = GeoJSONPolygon.model_validate(_polygon())
    assert polygon.to_shapely().is_valid


def test_rejects_non_polygon_type():
    with pytest.raises(ValidationError):
        GeoJSONPolygon.model_validate({"type": "MultiPolygon", "coordinates": [[_VALID_SQUARE]]})


def test_rejects_ring_with_fewer_than_four_points():
    with pytest.raises(ValidationError, match="at least 4 points"):
        GeoJSONPolygon.model_validate(_polygon([[76.0, 18.0], [76.01, 18.0], [76.0, 18.0]]))


def test_rejects_unclosed_ring():
    unclosed = [[76.0, 18.0], [76.01, 18.0], [76.01, 18.01], [76.0, 18.01]]  # first != last
    with pytest.raises(ValidationError, match="not closed"):
        GeoJSONPolygon.model_validate(_polygon(unclosed))


def test_rejects_multiple_rings_holes_not_supported():
    hole = [76.005, 18.005]
    with pytest.raises(ValidationError, match="single ring"):
        GeoJSONPolygon.model_validate(
            {"type": "Polygon", "coordinates": [_VALID_SQUARE, [hole, hole, hole, hole]]}
        )


@pytest.mark.parametrize(
    "bad_ring",
    [
        [[181.0, 18.0], [76.01, 18.0], [76.01, 18.01], [181.0, 18.0]],  # longitude > 180
        [[-181.0, 18.0], [76.01, 18.0], [76.01, 18.01], [-181.0, 18.0]],  # longitude < -180
        [[76.0, 91.0], [76.01, 18.0], [76.01, 18.01], [76.0, 91.0]],  # latitude > 90
        [[76.0, -91.0], [76.01, 18.0], [76.01, 18.01], [76.0, -91.0]],  # latitude < -90
    ],
)
def test_rejects_impossible_coordinates(bad_ring):
    with pytest.raises(ValidationError, match="out of valid range"):
        GeoJSONPolygon.model_validate(_polygon(bad_ring))


def test_rejects_self_intersecting_bowtie_polygon():
    # A classic bowtie/figure-8: crosses itself in the middle.
    bowtie = [[76.0, 18.0], [76.01, 18.01], [76.01, 18.0], [76.0, 18.01], [76.0, 18.0]]
    with pytest.raises(ValidationError, match="not a valid simple geometry"):
        GeoJSONPolygon.model_validate(_polygon(bowtie))


def test_rejects_zero_area_degenerate_polygon():
    # All points collinear — a line, not a polygon.
    line = [[76.0, 18.0], [76.01, 18.0], [76.02, 18.0], [76.0, 18.0]]
    with pytest.raises(ValidationError):
        GeoJSONPolygon.model_validate(_polygon(line))


def test_accepts_explicit_wgs84_crs():
    payload = _polygon(crs={"type": "name", "properties": {"name": "EPSG:4326"}})
    polygon = GeoJSONPolygon.model_validate(payload)
    assert polygon.crs is not None


def test_rejects_non_wgs84_crs():
    payload = _polygon(crs={"type": "name", "properties": {"name": "EPSG:3857"}})
    with pytest.raises(ValidationError, match="Unsupported CRS"):
        GeoJSONPolygon.model_validate(payload)
