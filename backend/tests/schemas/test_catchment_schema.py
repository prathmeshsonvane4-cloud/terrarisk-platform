"""Pure, offline tests for catchment request/response schemas (ticket
M4-001) — no database, no network. Mirrors test_farm_schema.py's exact
style; every rejection tested here is a request the future API must
reject at the parsing boundary, before it ever reaches application
logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import DelineationMethod
from app.schemas.catchment import (
    CatchmentCreateRequest,
    CatchmentResponse,
    CatchmentUploadRequest,
    GeoJSONMultiPolygon,
)

_VALID_SQUARE = [[76.0, 18.0], [76.01, 18.0], [76.01, 18.01], [76.0, 18.01], [76.0, 18.0]]
_VALID_SQUARE_2 = [[77.0, 19.0], [77.01, 19.0], [77.01, 19.01], [77.0, 19.01], [77.0, 19.0]]


def _multipolygon(polygons=None, **overrides):
    # `polygons if polygons is not None else ...`, not `polygons or ...`:
    # an explicitly empty list ([]) must stay empty, not be silently
    # replaced by the default (a bare `or` would do exactly that, since
    # [] is falsy).
    payload = {"type": "MultiPolygon", "coordinates": polygons if polygons is not None else [[_VALID_SQUARE]]}
    payload.update(overrides)
    return payload


class TestGeoJSONMultiPolygon:
    def test_valid_single_polygon_multipolygon_is_accepted(self):
        geometry = GeoJSONMultiPolygon.model_validate(_multipolygon())
        assert geometry.to_shapely().is_valid

    def test_valid_multi_part_multipolygon_is_accepted(self):
        """The whole reason Catchment.geometry is MULTIPOLYGON, not
        POLYGON — a real watershed is not guaranteed to be simply
        connected."""
        geometry = GeoJSONMultiPolygon.model_validate(_multipolygon([[_VALID_SQUARE], [_VALID_SQUARE_2]]))
        assert geometry.to_shapely().is_valid
        assert len(geometry.to_shapely().geoms) == 2

    def test_polygon_with_a_hole_is_accepted(self):
        """Unlike GeoJSONPolygon (farms), holes are structurally
        permitted here — a real watershed excluding an enclosed area is
        physically meaningful."""
        hole = [[76.002, 18.002], [76.008, 18.002], [76.008, 18.008], [76.002, 18.008], [76.002, 18.002]]
        geometry = GeoJSONMultiPolygon.model_validate(_multipolygon([[_VALID_SQUARE, hole]]))
        assert geometry.to_shapely().is_valid

    def test_rejects_non_multipolygon_type(self):
        with pytest.raises(ValidationError):
            GeoJSONMultiPolygon.model_validate({"type": "Polygon", "coordinates": [_VALID_SQUARE]})

    def test_rejects_empty_polygon_list(self):
        with pytest.raises(ValidationError, match="at least one polygon"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([]))

    def test_rejects_polygon_with_no_rings(self):
        with pytest.raises(ValidationError, match="no rings"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[]]))

    def test_rejects_ring_with_fewer_than_four_points(self):
        short_ring = [[76.0, 18.0], [76.01, 18.0], [76.0, 18.0]]
        with pytest.raises(ValidationError, match="at least 4 points"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[short_ring]]))

    def test_rejects_total_vertex_count_over_the_maximum(self):
        """Matches Catchment's own chk_catchment_vertex_count CHECK
        constraint bound exactly (2000) — the same request-path DoS
        prevention farm.py already documents for its own ring cap."""
        huge_ring = [[76.0 + i * 0.00001, 18.0 + i * 0.00001] for i in range(2001)]
        huge_ring.append(huge_ring[0])
        with pytest.raises(ValidationError, match="at most 2000 total vertices"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[huge_ring]]))

    def test_vertex_count_is_summed_across_every_ring_and_polygon(self):
        """The 2000 cap applies to the WHOLE MultiPolygon, not per-ring
        or per-polygon — two valid-sized rings that individually stay
        under the cap but sum over it must still be rejected."""
        big_ring_a = [[76.0 + i * 0.0001, 18.0] for i in range(1200)]
        big_ring_a.append(big_ring_a[0])
        big_ring_b = [[77.0 + i * 0.0001, 19.0] for i in range(1200)]
        big_ring_b.append(big_ring_b[0])
        with pytest.raises(ValidationError, match="at most 2000 total vertices"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[big_ring_a], [big_ring_b]]))

    def test_rejects_non_finite_coordinates(self):
        non_finite = [[76.0, 18.0], [float("nan"), 18.0], [76.01, 18.01], [76.0, 18.0]]
        with pytest.raises(ValidationError, match="not finite"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[non_finite]]))

    def test_rejects_unclosed_ring(self):
        unclosed = [[76.0, 18.0], [76.01, 18.0], [76.01, 18.01], [76.0, 18.01]]
        with pytest.raises(ValidationError, match="not closed"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[unclosed]]))

    @pytest.mark.parametrize(
        "bad_ring",
        [
            [[181.0, 18.0], [76.01, 18.0], [76.01, 18.01], [181.0, 18.0]],
            [[-181.0, 18.0], [76.01, 18.0], [76.01, 18.01], [-181.0, 18.0]],
            [[76.0, 91.0], [76.01, 18.0], [76.01, 18.01], [76.0, 91.0]],
            [[76.0, -91.0], [76.01, 18.0], [76.01, 18.01], [76.0, -91.0]],
        ],
    )
    def test_rejects_impossible_coordinates(self, bad_ring):
        with pytest.raises(ValidationError, match="out of valid range"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[bad_ring]]))

    def test_rejects_self_intersecting_bowtie_polygon(self):
        bowtie = [[76.0, 18.0], [76.01, 18.01], [76.01, 18.0], [76.0, 18.01], [76.0, 18.0]]
        with pytest.raises(ValidationError, match="not a valid geometry"):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[bowtie]]))

    def test_rejects_zero_area_degenerate_polygon(self):
        line = [[76.0, 18.0], [76.01, 18.0], [76.02, 18.0], [76.0, 18.0]]
        with pytest.raises(ValidationError):
            GeoJSONMultiPolygon.model_validate(_multipolygon([[line]]))

    def test_accepts_explicit_wgs84_crs(self):
        payload = _multipolygon(crs={"type": "name", "properties": {"name": "EPSG:4326"}})
        geometry = GeoJSONMultiPolygon.model_validate(payload)
        assert geometry.crs is not None

    def test_rejects_non_wgs84_crs(self):
        payload = _multipolygon(crs={"type": "name", "properties": {"name": "EPSG:3857"}})
        with pytest.raises(ValidationError, match="Unsupported CRS"):
            GeoJSONMultiPolygon.model_validate(payload)


class TestCatchmentCreateRequest:
    def test_valid_request_is_accepted(self):
        request = CatchmentCreateRequest.model_validate({"name": "Test Catchment", "geometry": _multipolygon()})
        assert request.name == "Test Catchment"
        assert request.organization_id is None
        assert request.admin_boundary_id is None

    def test_name_is_required(self):
        with pytest.raises(ValidationError, match="name"):
            CatchmentCreateRequest.model_validate({"geometry": _multipolygon()})

    def test_geometry_is_required(self):
        with pytest.raises(ValidationError, match="geometry"):
            CatchmentCreateRequest.model_validate({"name": "Test Catchment"})

    def test_empty_name_is_rejected(self):
        with pytest.raises(ValidationError):
            CatchmentCreateRequest.model_validate({"name": "", "geometry": _multipolygon()})

    def test_name_over_255_characters_is_rejected(self):
        with pytest.raises(ValidationError):
            CatchmentCreateRequest.model_validate({"name": "X" * 256, "geometry": _multipolygon()})

    def test_name_at_exactly_255_characters_is_accepted(self):
        request = CatchmentCreateRequest.model_validate({"name": "X" * 255, "geometry": _multipolygon()})
        assert len(request.name) == 255

    def test_optional_ids_accept_valid_uuids(self):
        org_id = uuid4()
        boundary_id = uuid4()
        request = CatchmentCreateRequest.model_validate(
            {
                "name": "Test Catchment",
                "geometry": _multipolygon(),
                "organization_id": str(org_id),
                "admin_boundary_id": str(boundary_id),
            }
        )
        assert request.organization_id == org_id
        assert request.admin_boundary_id == boundary_id

    def test_invalid_uuid_for_organization_id_is_rejected(self):
        with pytest.raises(ValidationError):
            CatchmentCreateRequest.model_validate(
                {"name": "Test Catchment", "geometry": _multipolygon(), "organization_id": "not-a-uuid"}
            )

    def test_invalid_geometry_is_rejected_by_the_nested_schema(self):
        with pytest.raises(ValidationError):
            CatchmentCreateRequest.model_validate({"name": "Test Catchment", "geometry": {"type": "Polygon"}})

    def test_delineation_method_is_not_an_accepted_field(self):
        """Deliberately not client-supplied — determined by which
        endpoint receives the request, not asserted by the caller."""
        request = CatchmentCreateRequest.model_validate(
            {"name": "Test Catchment", "geometry": _multipolygon(), "delineation_method": "auto_dem"}
        )
        assert not hasattr(request, "delineation_method")


class TestCatchmentUploadRequest:
    def test_valid_request_is_accepted(self):
        request = CatchmentUploadRequest.model_validate({"name": "Uploaded Catchment"})
        assert request.name == "Uploaded Catchment"
        assert request.organization_id is None

    def test_name_is_required(self):
        with pytest.raises(ValidationError):
            CatchmentUploadRequest.model_validate({})

    def test_no_geometry_field_exists_on_this_schema(self):
        """The boundary file itself is handled by FastAPI's UploadFile
        mechanism at the route layer, not this JSON-body schema."""
        assert "geometry" not in CatchmentUploadRequest.model_fields


@dataclass
class _FakeCatchmentOrmRow:
    """A plain object with matching attributes — proves
    CatchmentResponse.model_validate(..., from_attributes) works against
    an ORM-instance-shaped object, not just a dict."""

    id: UUID
    name: str
    area_ha: float
    delineation_method: DelineationMethod
    organization_id: UUID | None
    admin_boundary_id: UUID | None
    resolution_flags: list
    created_by: UUID
    created_at: datetime


def _fake_orm_row(**overrides) -> _FakeCatchmentOrmRow:
    defaults = dict(
        id=uuid4(),
        name="Test Catchment",
        area_ha=12.5,
        delineation_method=DelineationMethod.MANUAL,
        organization_id=None,
        admin_boundary_id=None,
        resolution_flags=["rainfall_sub_pixel"],
        created_by=uuid4(),
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return _FakeCatchmentOrmRow(**defaults)


class TestCatchmentResponse:
    def test_serializes_from_an_orm_like_object(self):
        row = _fake_orm_row()
        response = CatchmentResponse.model_validate(row)
        assert response.id == row.id
        assert response.name == row.name
        assert response.delineation_method == DelineationMethod.MANUAL

    def test_no_geometry_field_on_the_response(self):
        """Mirrors FarmResponse's exact convention: no raw geometry in
        the basic response."""
        assert "geometry" not in CatchmentResponse.model_fields

    def test_round_trips_through_dump_and_validate(self):
        row = _fake_orm_row()
        response = CatchmentResponse.model_validate(row)
        dumped = response.model_dump(mode="json")
        rebuilt = CatchmentResponse.model_validate(dumped)
        assert rebuilt == response

    def test_json_serialization_produces_iso_datetime_and_string_uuids(self):
        row = _fake_orm_row()
        response = CatchmentResponse.model_validate(row)
        dumped = response.model_dump(mode="json")
        assert isinstance(dumped["id"], str)
        assert isinstance(dumped["created_at"], str)
        assert dumped["delineation_method"] == "manual"

    def test_missing_required_field_is_rejected(self):
        row = _fake_orm_row()
        payload = CatchmentResponse.model_validate(row).model_dump(mode="json")
        del payload["area_ha"]
        with pytest.raises(ValidationError, match="area_ha"):
            CatchmentResponse.model_validate(payload)

    def test_invalid_delineation_method_value_is_rejected(self):
        row = _fake_orm_row()
        payload = CatchmentResponse.model_validate(row).model_dump(mode="json")
        payload["delineation_method"] = "not-a-real-method"
        with pytest.raises(ValidationError):
            CatchmentResponse.model_validate(payload)

    def test_nullable_fields_accept_none(self):
        row = _fake_orm_row(organization_id=None, admin_boundary_id=None)
        response = CatchmentResponse.model_validate(row)
        assert response.organization_id is None
        assert response.admin_boundary_id is None

    def test_empty_resolution_flags_list_is_valid(self):
        row = _fake_orm_row(resolution_flags=[])
        response = CatchmentResponse.model_validate(row)
        assert response.resolution_flags == []
