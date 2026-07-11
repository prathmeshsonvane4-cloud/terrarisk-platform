"""Integration tests for the farm endpoints, against real PostGIS and real
JWT auth end to end — proves authorization is actually enforced at the
HTTP layer, not just assumed from the dependency's unit tests.

Uses httpx.AsyncClient + ASGITransport rather than FastAPI's sync
TestClient: TestClient runs the ASGI app through anyio's BlockingPortal in
a separate internal thread/event loop, which corrupts the shared database
engine's connection pool when a test also opens connections directly via
AsyncSessionLocal() in pytest-asyncio's own (session-scoped) loop —
surfaces as "Future ... attached to a different loop". Keeping the whole
test on one event loop (fixture setup, the HTTP call, and cleanup) avoids
this entirely, and is the standard pattern for testing async FastAPI apps.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import Polygon
from sqlalchemy import delete, text

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.main import app
from app.models.admin import AdminBoundary
from app.models.enums import BoundaryLevel, UserRole
from app.models.farm import FarmPolygon
from app.models.user import AppUser

_VALID_SQUARE = [[76.0, 18.0], [76.01, 18.0], [76.01, 18.01], [76.0, 18.01], [76.0, 18.0]]


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
async def village_and_users():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    async with AsyncSessionLocal() as db:
        village = AdminBoundary(
            level=BoundaryLevel.VILLAGE,
            name=f"Test Village {uuid4().hex[:8]}",
            geometry=from_shape(
                Polygon([(76.0, 18.0), (76.5, 18.0), (76.5, 18.5), (76.0, 18.5), (76.0, 18.0)]), srid=4326
            ),
        )
        officer = AppUser(
            email=f"officer-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
        )
        risk_officer = AppUser(
            email=f"risk-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Risk Officer",
            role=UserRole.RISK_OFFICER,
            is_active=True,
        )
        outsider = AppUser(
            email=f"outsider-{uuid4().hex[:8]}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Different Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
        )
        db.add_all([village, officer, risk_officer, outsider])
        await db.commit()
        await db.refresh(village)
        await db.refresh(officer)
        await db.refresh(risk_officer)
        await db.refresh(outsider)

    yield {"village": village, "officer": officer, "risk_officer": risk_officer, "outsider": outsider}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(FarmPolygon).where(FarmPolygon.village_id == village.id))
        await db.execute(delete(AppUser).where(AppUser.id.in_([officer.id, risk_officer.id, outsider.id])))
        await db.execute(delete(AdminBoundary).where(AdminBoundary.id == village.id))
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str = "correct-password") -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_create_farm_succeeds_for_credit_officer_and_computes_area_server_side(api_client, village_and_users):
    token = await _login(api_client, village_and_users["officer"].email)

    response = await api_client.post(
        "/api/v1/farms",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "village_id": str(village_and_users["village"].id),
            "geometry": {"type": "Polygon", "coordinates": [_VALID_SQUARE]},
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["area_ha"] > 0
    # drawn_by must be the authenticated officer, never something the
    # client could have supplied — the request body has no such field.
    assert body["drawn_by"] == str(village_and_users["officer"].id)


@pytest.mark.asyncio
async def test_create_farm_rejects_unauthenticated_request(api_client, village_and_users):
    response = await api_client.post(
        "/api/v1/farms",
        json={
            "village_id": str(village_and_users["village"].id),
            "geometry": {"type": "Polygon", "coordinates": [_VALID_SQUARE]},
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_farm_rejects_role_without_farm_drawing_permission(api_client, village_and_users):
    """A Risk Officer is a real, authenticated user — but drawing a farm
    boundary is a Credit Officer / Branch Manager action, not theirs."""
    token = await _login(api_client, village_and_users["risk_officer"].email)

    response = await api_client.post(
        "/api/v1/farms",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "village_id": str(village_and_users["village"].id),
            "geometry": {"type": "Polygon", "coordinates": [_VALID_SQUARE]},
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_farm_rejects_unknown_village_id(api_client, village_and_users):
    token = await _login(api_client, village_and_users["officer"].email)

    response = await api_client.post(
        "/api/v1/farms",
        headers={"Authorization": f"Bearer {token}"},
        json={"village_id": str(uuid4()), "geometry": {"type": "Polygon", "coordinates": [_VALID_SQUARE]}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_farm_rejects_village_id_that_is_not_a_village(api_client, village_and_users):
    """A district-level (or any non-village) AdminBoundary id must not be
    accepted as a farm's village_id, even though it's a valid UUID that
    exists in the table."""
    token = await _login(api_client, village_and_users["officer"].email)

    async with AsyncSessionLocal() as db:
        district = AdminBoundary(
            level=BoundaryLevel.DISTRICT,
            name=f"Test District {uuid4().hex[:8]}",
            geometry=from_shape(
                Polygon([(76.0, 18.0), (77.0, 18.0), (77.0, 19.0), (76.0, 19.0), (76.0, 18.0)]), srid=4326
            ),
        )
        db.add(district)
        await db.commit()
        await db.refresh(district)
        district_id = district.id

    try:
        response = await api_client.post(
            "/api/v1/farms",
            headers={"Authorization": f"Bearer {token}"},
            json={"village_id": str(district_id), "geometry": {"type": "Polygon", "coordinates": [_VALID_SQUARE]}},
        )
        assert response.status_code == 422
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AdminBoundary).where(AdminBoundary.id == district_id))
            await db.commit()


@pytest.mark.asyncio
async def test_create_farm_rejects_malformed_geometry_at_request_boundary(api_client, village_and_users):
    """Self-intersecting polygon — the API must reject it with a 422
    before it ever reaches the database, not with a 500 from a PostGIS
    constraint violation."""
    token = await _login(api_client, village_and_users["officer"].email)
    bowtie = [[76.0, 18.0], [76.01, 18.01], [76.01, 18.0], [76.0, 18.01], [76.0, 18.0]]

    response = await api_client.post(
        "/api/v1/farms",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "village_id": str(village_and_users["village"].id),
            "geometry": {"type": "Polygon", "coordinates": [bowtie]},
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_farm_returns_404_for_unknown_id(api_client, village_and_users):
    token = await _login(api_client, village_and_users["officer"].email)
    response = await api_client.get(f"/api/v1/farms/{uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_farm_rejects_invalid_token(api_client):
    response = await api_client.get(f"/api/v1/farms/{uuid4()}", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_farm_rejects_malformed_uuid_path_param(api_client, village_and_users):
    token = await _login(api_client, village_and_users["officer"].email)
    response = await api_client.get("/api/v1/farms/not-a-valid-uuid", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_farm_returns_created_farm(api_client, village_and_users):
    token = await _login(api_client, village_and_users["officer"].email)
    create_response = await api_client.post(
        "/api/v1/farms",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "village_id": str(village_and_users["village"].id),
            "geometry": {"type": "Polygon", "coordinates": [_VALID_SQUARE]},
        },
    )
    farm_id = create_response.json()["id"]

    response = await api_client.get(f"/api/v1/farms/{farm_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["id"] == farm_id


@pytest.mark.asyncio
async def test_get_farm_rejects_user_outside_owner_or_branch(api_client, village_and_users):
    """A farm drawn by one officer must not be readable by an unrelated
    officer with no shared branch — same not-found-vs-forbidden guard as
    jobs/reports (app/api/deps.py::user_can_access_owned_resource)."""
    officer_token = await _login(api_client, village_and_users["officer"].email)
    create_response = await api_client.post(
        "/api/v1/farms",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "village_id": str(village_and_users["village"].id),
            "geometry": {"type": "Polygon", "coordinates": [_VALID_SQUARE]},
        },
    )
    farm_id = create_response.json()["id"]

    outsider_token = await _login(api_client, village_and_users["outsider"].email)
    response = await api_client.get(
        f"/api/v1/farms/{farm_id}", headers={"Authorization": f"Bearer {outsider_token}"}
    )
    assert response.status_code == 404
