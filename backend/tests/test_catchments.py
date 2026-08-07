"""Integration tests for POST /catchments (ticket M4-003), against real
PostGIS and real JWT auth end to end — mirrors tests/test_farms.py's
exact pattern and its documented reason for using httpx.AsyncClient +
ASGITransport (a shared event loop across fixture setup, the HTTP call,
and cleanup) rather than FastAPI's sync TestClient.
"""

from __future__ import annotations

import io
import json
import zipfile
from uuid import UUID, uuid4

import pyproj
import pytest
import pytest_asyncio
import shapefile
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from app.api.catchments import (
    _ET_PIXEL_FLOOR_HA,
    _RAINFALL_PIXEL_AREA_HA,
    _derive_resolution_flags,
)
from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.main import app
from app.models.catchment import Catchment
from app.models.enums import JobStatus, JobType, OrganizationType, UserRole
from app.models.job import Job
from app.models.organization import Organization
from app.models.user import AppUser
from app.models.water_balance import RechargeStressScore, WaterBalanceResult

_VALID_SQUARE = [[76.0, 18.0], [76.01, 18.0], [76.01, 18.01], [76.0, 18.01], [76.0, 18.0]]
_VALID_SQUARE_CW = [[76.0, 18.0], [76.0, 18.01], [76.01, 18.01], [76.01, 18.0], [76.0, 18.0]]


async def _database_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def api_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def users_and_org():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    async with AsyncSessionLocal() as db:
        organization = Organization(name=f"Test Org {uuid4().hex[:8]}", org_type=OrganizationType.NGO)
        officer = AppUser(
            email=f"officer-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Programme Officer",
            role=UserRole.PROGRAMME_OFFICER,
            is_active=True,
        )
        admin = AppUser(
            email=f"admin-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Programme Admin",
            role=UserRole.PROGRAMME_ADMIN,
            is_active=True,
        )
        credit_officer = AppUser(
            email=f"credit-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Bank Credit Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
        )
        db.add_all([organization, officer, admin, credit_officer])
        await db.commit()
        await db.refresh(organization)
        await db.refresh(officer)
        await db.refresh(admin)
        await db.refresh(credit_officer)

    yield {"organization": organization, "officer": officer, "admin": admin, "credit_officer": credit_officer}

    async with AsyncSessionLocal() as db:
        # Job.created_by is a non-nullable FK to app_user with no
        # ondelete — any water-report job created by these users
        # (ticket M4-006) must be cleared first or the AppUser delete
        # below would fail with an IntegrityError, same reasoning as
        # test_reports.py's own scenario fixture teardown.
        #
        # WaterBalanceResult/RechargeStressScore must be cleared before
        # Catchment for the same reason, one level deeper: a real,
        # live-GEE water-report trigger test in this file (unlike most
        # others here) can actually complete and persist both rows —
        # deleting the Catchment first then violates their FK. Same
        # ordering test_water_report_detail.py/test_water_report_history.py
        # already use; this fixture just never needed it before those
        # two trigger-and-complete tests existed in this file.
        catchments = (
            await db.execute(select(Catchment.id).where(Catchment.created_by.in_([officer.id, admin.id, credit_officer.id])))
        ).scalars().all()
        if catchments:
            await db.execute(delete(RechargeStressScore).where(RechargeStressScore.catchment_id.in_(catchments)))
            await db.execute(delete(WaterBalanceResult).where(WaterBalanceResult.catchment_id.in_(catchments)))
        await db.execute(delete(Job).where(Job.created_by.in_([officer.id, admin.id, credit_officer.id])))
        await db.execute(delete(Catchment).where(Catchment.created_by.in_([officer.id, admin.id, credit_officer.id])))
        await db.execute(delete(AppUser).where(AppUser.id.in_([officer.id, admin.id, credit_officer.id])))
        await db.execute(delete(Organization).where(Organization.id == organization.id))
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str = "correct-password") -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _payload(name: str | None = None, **overrides) -> dict:
    payload = {
        "name": name or f"Test Catchment {uuid4().hex[:8]}",
        "geometry": {"type": "MultiPolygon", "coordinates": [[_VALID_SQUARE]]},
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_create_catchment_succeeds_for_programme_officer_and_returns_catchment_response(
    api_client, users_and_org
):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, json=_payload()
    )

    assert response.status_code == 201, response.text
    body = response.json()
    # Response schema: every CatchmentResponse field present, correctly
    # typed, and geometry deliberately absent (M4-001's own convention).
    assert set(body.keys()) == {
        "id",
        "name",
        "area_ha",
        "delineation_method",
        "organization_id",
        "admin_boundary_id",
        "resolution_flags",
        "created_by",
        "created_at",
    }
    assert body["delineation_method"] == "manual"
    assert body["created_by"] == str(users_and_org["officer"].id)
    # Previously pinned to [] — which was pinning the fact that the field
    # was never populated, not a property of this catchment. It is now
    # derived from area at creation, and this fixture's polygon is well
    # under one CHIRPS rainfall pixel (~3,000 ha), so the sub-pixel
    # disclosure is the correct result rather than an empty list.
    assert body["resolution_flags"] == ["rainfall_sub_pixel"]


@pytest.mark.asyncio
async def test_area_ha_is_computed_server_side_not_trusted_from_the_client(api_client, users_and_org):
    """The request body has no area_ha field at all — this proves the
    response value is a real PostGIS computation, not an echo."""
    token = await _login(api_client, users_and_org["officer"].email)

    response = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, json=_payload()
    )

    assert response.status_code == 201, response.text
    area_ha = response.json()["area_ha"]
    assert area_ha > 0
    # The drawn square is ~0.01deg x 0.01deg near the equator-ish
    # latitude used throughout this test suite — order-of-magnitude
    # sanity bound, not a precise expected value (that's PostGIS's own,
    # already-trusted geodesic computation, not something to re-derive
    # by hand here).
    assert 0.5 < area_ha < 50000


@pytest.mark.asyncio
async def test_create_catchment_rejects_unauthenticated_request(api_client, users_and_org):
    response = await api_client.post("/api/v1/catchments", json=_payload())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_catchment_rejects_role_without_catchment_creation_permission(api_client, users_and_org):
    """A real, authenticated user — but a bank Credit Officer has no
    Water Intelligence role at all, so this must be 403, not 201."""
    token = await _login(api_client, users_and_org["credit_officer"].email)

    response = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, json=_payload()
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_programme_admin_can_also_create_a_catchment(api_client, users_and_org):
    token = await _login(api_client, users_and_org["admin"].email)

    response = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, json=_payload()
    )

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_create_catchment_rejects_malformed_geometry_at_request_boundary(api_client, users_and_org):
    """Self-intersecting polygon — the API must reject it with a 422
    before it ever reaches the database, not with a 500 from a PostGIS
    constraint violation."""
    token = await _login(api_client, users_and_org["officer"].email)
    bowtie = [[76.0, 18.0], [76.01, 18.01], [76.01, 18.0], [76.0, 18.01], [76.0, 18.0]]

    response = await api_client.post(
        "/api/v1/catchments",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload(geometry={"type": "MultiPolygon", "coordinates": [[bowtie]]}),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_catchment_rejects_unknown_organization_id(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await api_client.post(
        "/api/v1/catchments",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload(organization_id=str(uuid4())),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_catchment_rejects_unknown_admin_boundary_id(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await api_client.post(
        "/api/v1/catchments",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload(admin_boundary_id=str(uuid4())),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_name_within_the_same_organization_is_rejected(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    org_id = str(users_and_org["organization"].id)
    name = f"Duplicate Test {uuid4().hex[:8]}"

    first = await api_client.post(
        "/api/v1/catchments",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload(name=name, organization_id=org_id),
    )
    assert first.status_code == 201, first.text

    second = await api_client.post(
        "/api/v1/catchments",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload(name=name, organization_id=org_id),
    )

    assert second.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_name_without_an_organization_is_scoped_to_the_creator(api_client, users_and_org):
    """No organization_id given — the duplicate check falls back to the
    caller's own catchments, not a global name lock two unrelated users
    would otherwise collide on."""
    officer_token = await _login(api_client, users_and_org["officer"].email)
    admin_token = await _login(api_client, users_and_org["admin"].email)
    name = f"Personal Catchment {uuid4().hex[:8]}"

    first = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {officer_token}"}, json=_payload(name=name)
    )
    assert first.status_code == 201, first.text

    same_creator_again = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {officer_token}"}, json=_payload(name=name)
    )
    assert same_creator_again.status_code == 409

    different_creator = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {admin_token}"}, json=_payload(name=name)
    )
    assert different_creator.status_code == 201, different_creator.text


@pytest.mark.asyncio
async def test_same_name_in_a_different_organization_is_allowed(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    name = f"Cross-Org Name {uuid4().hex[:8]}"

    async with AsyncSessionLocal() as db:
        other_org = Organization(name=f"Other Org {uuid4().hex[:8]}", org_type=OrganizationType.GOVERNMENT)
        db.add(other_org)
        await db.commit()
        await db.refresh(other_org)

    try:
        first = await api_client.post(
            "/api/v1/catchments",
            headers={"Authorization": f"Bearer {token}"},
            json=_payload(name=name, organization_id=str(users_and_org["organization"].id)),
        )
        assert first.status_code == 201, first.text

        second = await api_client.post(
            "/api/v1/catchments",
            headers={"Authorization": f"Bearer {token}"},
            json=_payload(name=name, organization_id=str(other_org.id)),
        )
        assert second.status_code == 201, second.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Catchment).where(Catchment.organization_id == other_org.id))
            await db.execute(delete(Organization).where(Organization.id == other_org.id))
            await db.commit()


# =====================================================================
# POST /catchments/upload (ticket M4-004)
# =====================================================================


def _geojson_bytes() -> bytes:
    return json.dumps({"type": "Polygon", "coordinates": [_VALID_SQUARE]}).encode("utf-8")


def _kml_bytes() -> bytes:
    ring_text = " ".join(f"{lon},{lat},0" for lon, lat in _VALID_SQUARE)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>{ring_text}</coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>""".encode("utf-8")


def _shapefile_zip_bytes() -> bytes:
    shp_buf, shx_buf, dbf_buf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp_buf, shx=shx_buf, dbf=dbf_buf, shapeType=shapefile.POLYGON)
    writer.field("name", "C")
    writer.poly([_VALID_SQUARE_CW])  # clockwise exterior ring, per Shapefile's own orientation convention
    writer.record("test")
    writer.close()

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as archive:
        archive.writestr("boundary.shp", shp_buf.getvalue())
        archive.writestr("boundary.shx", shx_buf.getvalue())
        archive.writestr("boundary.dbf", dbf_buf.getvalue())
        archive.writestr("boundary.prj", pyproj.CRS.from_epsg(4326).to_wkt())
    return zip_buf.getvalue()


async def _upload(
    api_client: AsyncClient,
    token: str,
    filename: str,
    content: bytes,
    content_type: str,
    *,
    name: str | None = None,
    organization_id: str | None = None,
) -> object:
    data = {"name": name or f"Uploaded Catchment {uuid4().hex[:8]}"}
    if organization_id is not None:
        data["organization_id"] = organization_id
    return await api_client.post(
        "/api/v1/catchments/upload",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        files={"file": (filename, content, content_type)},
    )


@pytest.mark.asyncio
async def test_upload_geojson_creates_a_catchment_with_upload_delineation_method(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await _upload(api_client, token, "boundary.geojson", _geojson_bytes(), "application/geo+json")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["delineation_method"] == "upload"
    assert body["area_ha"] > 0
    assert body["created_by"] == str(users_and_org["officer"].id)


@pytest.mark.asyncio
async def test_upload_kml_creates_a_catchment(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await _upload(api_client, token, "boundary.kml", _kml_bytes(), "application/vnd.google-earth.kml+xml")

    assert response.status_code == 201, response.text
    assert response.json()["delineation_method"] == "upload"


@pytest.mark.asyncio
async def test_upload_shapefile_creates_a_catchment(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await _upload(api_client, token, "boundary.zip", _shapefile_zip_bytes(), "application/zip")

    assert response.status_code == 201, response.text
    assert response.json()["delineation_method"] == "upload"


@pytest.mark.asyncio
async def test_upload_invalid_geometry_file_is_rejected(api_client, users_and_org):
    """Malformed JSON — the same "422 before it ever reaches the
    database" discipline the manual-draw endpoint's schema validation
    already guarantees, here enforced by boundary_parser.py instead."""
    token = await _login(api_client, users_and_org["officer"].email)

    response = await _upload(api_client, token, "boundary.geojson", b"{not valid json", "application/geo+json")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_unsupported_format_is_rejected(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await _upload(api_client, token, "boundary.txt", b"some content", "text/plain")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_empty_file_is_rejected(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await _upload(api_client, token, "boundary.geojson", b"", "application/geo+json")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_duplicate_name_is_rejected(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    name = f"Duplicate Upload {uuid4().hex[:8]}"
    org_id = str(users_and_org["organization"].id)

    first = await _upload(
        api_client, token, "boundary.geojson", _geojson_bytes(), "application/geo+json", name=name, organization_id=org_id
    )
    assert first.status_code == 201, first.text

    second = await _upload(
        api_client, token, "boundary.geojson", _geojson_bytes(), "application/geo+json", name=name, organization_id=org_id
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_upload_rejects_unauthenticated_request(api_client, users_and_org):
    response = await api_client.post(
        "/api/v1/catchments/upload",
        data={"name": "Unauthorized Upload"},
        files={"file": ("boundary.geojson", _geojson_bytes(), "application/geo+json")},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_rejects_role_without_catchment_creation_permission(api_client, users_and_org):
    token = await _login(api_client, users_and_org["credit_officer"].email)

    response = await _upload(api_client, token, "boundary.geojson", _geojson_bytes(), "application/geo+json")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upload_reuses_the_same_area_computation_as_manual_create(api_client, users_and_org):
    """The uploaded boundary is the identical square _VALID_SQUARE the
    manual-create tests use — proves both endpoints compute area through
    the same shared persistence path, not two independently-behaving
    implementations."""
    token = await _login(api_client, users_and_org["officer"].email)

    manual = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, json=_payload()
    )
    uploaded = await _upload(api_client, token, "boundary.geojson", _geojson_bytes(), "application/geo+json")

    assert manual.status_code == 201, manual.text
    assert uploaded.status_code == 201, uploaded.text
    assert manual.json()["area_ha"] == pytest.approx(uploaded.json()["area_ha"])


# =====================================================================
# GET /catchments, GET /catchments/{catchment_id} (ticket M4-005)
# =====================================================================


async def _create(api_client: AsyncClient, token: str, **overrides) -> dict:
    response = await api_client.post(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, json=_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_list_catchments_returns_only_the_callers_own_catchments(api_client, users_and_org):
    officer_token = await _login(api_client, users_and_org["officer"].email)
    admin_token = await _login(api_client, users_and_org["admin"].email)

    mine = await _create(api_client, officer_token)
    await _create(api_client, admin_token)  # a different creator's catchment — must not appear

    response = await api_client.get("/api/v1/catchments", headers={"Authorization": f"Bearer {officer_token}"})

    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()]
    assert mine["id"] in ids
    assert all(item["created_by"] == str(users_and_org["officer"].id) for item in response.json())


@pytest.mark.asyncio
async def test_get_catchment_detail_success(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    created = await _create(api_client, token)

    response = await api_client.get(f"/api/v1/catchments/{created['id']}", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    body = response.json()
    # The detail endpoint returns everything the list endpoint does, plus
    # the analysed geometry (CatchmentDetailResponse) — the list/compare/
    # priority-queue screens fetch CatchmentResponse in bulk and must
    # never carry a polygon per row, so this field only exists here.
    assert body == {**created, "geometry": body["geometry"]}
    assert body["geometry"]["type"] == "MultiPolygon"


@pytest.mark.asyncio
async def test_get_catchment_returns_404_for_an_unknown_id(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await api_client.get(f"/api/v1/catchments/{uuid4()}", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_catchment_returns_404_not_403_for_another_users_catchment(api_client, users_and_org):
    """IDOR prevention, app/api/farms.py::get_farm's exact convention: a
    catchment that exists but belongs to someone else must be
    indistinguishable from one that was never created — 404, never a 403
    that would confirm the id is real."""
    officer_token = await _login(api_client, users_and_org["officer"].email)
    admin_token = await _login(api_client, users_and_org["admin"].email)
    other_catchment = await _create(api_client, admin_token)

    response = await api_client.get(
        f"/api/v1/catchments/{other_catchment['id']}", headers={"Authorization": f"Bearer {officer_token}"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_catchments_rejects_unauthenticated_request(api_client, users_and_org):
    response = await api_client.get("/api/v1/catchments")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_catchment_rejects_unauthenticated_request(api_client, users_and_org):
    response = await api_client.get(f"/api/v1/catchments/{uuid4()}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_catchments_rejects_role_without_permission(api_client, users_and_org):
    """A bank Credit Officer is a real, authenticated user — Water
    Intelligence data is simply not their product, hence 403 rather than
    an (empty, but successful) 200."""
    token = await _login(api_client, users_and_org["credit_officer"].email)

    response = await api_client.get("/api/v1/catchments", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_catchment_rejects_role_without_permission(api_client, users_and_org):
    token = await _login(api_client, users_and_org["credit_officer"].email)

    response = await api_client.get(f"/api/v1/catchments/{uuid4()}", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_pagination_limits_page_size_and_reports_total_count_header(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    created = [await _create(api_client, token) for _ in range(3)]

    first_page = await api_client.get(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, params={"limit": 2, "offset": 0}
    )
    second_page = await api_client.get(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, params={"limit": 2, "offset": 2}
    )

    assert first_page.status_code == 200, first_page.text
    assert len(first_page.json()) == 2
    assert int(first_page.headers["X-Total-Count"]) >= 3

    assert second_page.status_code == 200, second_page.text
    # No overlap between the two pages.
    first_ids = {item["id"] for item in first_page.json()}
    second_ids = {item["id"] for item in second_page.json()}
    assert first_ids.isdisjoint(second_ids)
    # Every created catchment is accounted for across both pages (order
    # is newest-first, so all 3 of this test's own catchments land in
    # the first two pages of 2).
    all_ids = first_ids | second_ids
    assert {c["id"] for c in created}.issubset(all_ids)


@pytest.mark.asyncio
async def test_pagination_rejects_page_size_over_the_maximum(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)

    response = await api_client.get(
        "/api/v1/catchments", headers={"Authorization": f"Bearer {token}"}, params={"limit": 201}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_organization_isolation_across_different_creators(api_client, users_and_org):
    """Two catchments tagged to two DIFFERENT organizations, created by
    two DIFFERENT users — proves a catchment's organization_id tag alone
    never leaks it into another user's list/detail view (see module
    docstring for why the underlying mechanism is creator-based, not
    org-membership-based)."""
    officer_token = await _login(api_client, users_and_org["officer"].email)
    admin_token = await _login(api_client, users_and_org["admin"].email)

    async with AsyncSessionLocal() as db:
        org_a = Organization(name=f"Org A {uuid4().hex[:8]}", org_type=OrganizationType.NGO)
        org_b = Organization(name=f"Org B {uuid4().hex[:8]}", org_type=OrganizationType.GOVERNMENT)
        db.add_all([org_a, org_b])
        await db.commit()
        await db.refresh(org_a)
        await db.refresh(org_b)

    try:
        catchment_a = await _create(api_client, officer_token, organization_id=str(org_a.id))
        catchment_b = await _create(api_client, admin_token, organization_id=str(org_b.id))

        officer_list = await api_client.get("/api/v1/catchments", headers={"Authorization": f"Bearer {officer_token}"})
        officer_ids = {item["id"] for item in officer_list.json()}
        assert catchment_a["id"] in officer_ids
        assert catchment_b["id"] not in officer_ids

        forbidden_get = await api_client.get(
            f"/api/v1/catchments/{catchment_b['id']}", headers={"Authorization": f"Bearer {officer_token}"}
        )
        assert forbidden_get.status_code == 404
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Catchment).where(Catchment.organization_id.in_([org_a.id, org_b.id])))
            await db.execute(delete(Organization).where(Organization.id.in_([org_a.id, org_b.id])))
            await db.commit()


# =====================================================================
# POST /catchments/{catchment_id}/water-reports (ticket M4-006; wired to
# a real pipeline in M5-002)
#
# This module never mocks GEEHydrologyProvider/GeeProvider (unlike
# tests/test_water_report_job_execution.py, which exists specifically to
# exercise the real-pipeline success/failure paths against fakes) — so
# the trigger below still reaches a terminal FAILED status here, but for
# a different, still-honest reason than before M5-002: this test
# environment has no live GEE credentials configured (confirmed
# throughout this codebase's test suite — every live-GEE test skips the
# same way). The job must still fail immediately with the generic
# message, never hang at PENDING, exactly like
# test_reports.py's own credential-failure test.
# =====================================================================


@pytest.mark.asyncio
async def test_trigger_water_report_succeeds_and_job_reaches_a_terminal_status(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    catchment = await _create(api_client, token)

    response = await api_client.post(
        f"/api/v1/catchments/{catchment['id']}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    job_response = await api_client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert job_response.status_code == 200
    job_json = job_response.json()
    # Background task runs synchronously within the ASGI test transport,
    # same as test_reports.py's own trigger_report tests.
    assert job_json["status"] == "failed", (
        "no live GEE credentials are configured in this test environment — the job must fail "
        f"honestly, not hang at PENDING (status was {job_json['status']!r})"
    )
    assert job_json["error_message"] == "Water report generation failed. Please retry; contact support if this persists."


@pytest.mark.asyncio
async def test_trigger_water_report_creates_a_catchment_water_report_job_row(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    catchment = await _create(api_client, token)

    response = await api_client.post(
        f"/api/v1/catchments/{catchment['id']}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )
    job_id = response.json()["job_id"]

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        assert job.type == JobType.CATCHMENT_WATER_REPORT
        assert job.entity_id == UUID(catchment["id"])
        assert job.created_by == users_and_org["officer"].id


@pytest.mark.asyncio
async def test_trigger_water_report_rejects_duplicate_in_flight_request(api_client, users_and_org):
    """A second trigger while the first is still pending/running must be
    rejected as a conflict, not silently start a second job — mirrors
    test_reports.py::test_trigger_report_rejects_duplicate_in_flight_request."""
    token = await _login(api_client, users_and_org["officer"].email)
    catchment = await _create(api_client, token)

    async with AsyncSessionLocal() as db:
        stuck_job = Job(
            type=JobType.CATCHMENT_WATER_REPORT,
            status=JobStatus.RUNNING,
            entity_id=UUID(catchment["id"]),
            created_by=users_and_org["officer"].id,
        )
        db.add(stuck_job)
        await db.commit()

    response = await api_client.post(
        f"/api/v1/catchments/{catchment['id']}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["job_id"] == str(stuck_job.id)


@pytest.mark.asyncio
async def test_trigger_water_report_rejects_unauthenticated_request(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    catchment = await _create(api_client, token)

    response = await api_client.post(f"/api/v1/catchments/{catchment['id']}/water-reports")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_trigger_water_report_rejects_role_without_catchment_permission(api_client, users_and_org):
    """A bank Credit Officer is a real, authenticated user — but Water
    Intelligence is not their product; same 403 as create_catchment's
    own role gate."""
    officer_token = await _login(api_client, users_and_org["officer"].email)
    catchment = await _create(api_client, officer_token)

    credit_officer_token = await _login(api_client, users_and_org["credit_officer"].email)
    response = await api_client.post(
        f"/api/v1/catchments/{catchment['id']}/water-reports",
        headers={"Authorization": f"Bearer {credit_officer_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_trigger_water_report_returns_404_for_unknown_catchment(api_client, users_and_org):
    token = await _login(api_client, users_and_org["officer"].email)
    response = await api_client.post(
        f"/api/v1/catchments/{uuid4()}/water-reports", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_trigger_water_report_returns_404_for_a_catchment_owned_by_someone_else(api_client, users_and_org):
    """Same IDOR-safe discipline as get_catchment: a catchment outside
    the caller's own scope must 404, not succeed and not 403 — proven
    here for the officer/admin pair, and that triggering never starts a
    real, billed pipeline run for a catchment the caller has no claim to."""
    owner_token = await _login(api_client, users_and_org["officer"].email)
    catchment = await _create(api_client, owner_token)

    other_token = await _login(api_client, users_and_org["admin"].email)
    response = await api_client.post(
        f"/api/v1/catchments/{catchment['id']}/water-reports", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert response.status_code == 404

    async with AsyncSessionLocal() as db:
        jobs = (await db.execute(select(Job).where(Job.created_by == users_and_org["admin"].id))).scalars().all()
        assert jobs == []


class TestResolutionFlagDerivation:
    """`_derive_resolution_flags` decides whether a catchment is too small
    for a given satellite input to describe it, rather than describing the
    region it sits inside.

    These are pure unit tests against the helper, not the endpoint: the
    thresholds are the scientific claim worth pinning, and driving them
    through catchment creation would need geometries of a precise real-
    world area, which is a projection exercise, not a test of this rule.
    """

    def test_village_scale_catchment_is_rainfall_sub_pixel_but_not_et_sub_pixel(self):
        """The common real case this exists for. A typical Raichur village
        (~143 ha) is ~1/20th of one CHIRPS rainfall pixel (~3,000 ha), so
        its "rainfall" is a regional value — but it still spans ~5.7 MODIS
        ET pixels (25 ha each), which genuinely resolve it. Flagging both,
        or neither, would both be wrong."""
        assert _derive_resolution_flags(143.0) == ["rainfall_sub_pixel"]

    def test_tiny_catchment_is_sub_pixel_for_both_inputs(self):
        assert _derive_resolution_flags(10.0) == ["rainfall_sub_pixel", "et_sub_pixel"]

    def test_large_catchment_carries_no_flags(self):
        """A catchment bigger than one rainfall pixel needs no disclosure —
        the flags must not fire for everything, or they stop carrying
        information."""
        assert _derive_resolution_flags(5000.0) == []

    def test_thresholds_are_exclusive_at_the_boundary(self):
        """Exactly one pixel is resolved, not sub-pixel — pinned because an
        off-by-one on a `<` vs `<=` here silently changes which catchments
        disclose a limitation."""
        assert _derive_resolution_flags(_RAINFALL_PIXEL_AREA_HA) == []
        assert _derive_resolution_flags(_ET_PIXEL_FLOOR_HA) == ["rainfall_sub_pixel"]

    def test_flag_order_is_stable(self):
        """Flags are persisted and compared across reports, so their order
        must not depend on dict/set iteration."""
        assert _derive_resolution_flags(1.0) == _derive_resolution_flags(1.0)
        assert _derive_resolution_flags(1.0)[0] == "rainfall_sub_pixel"
