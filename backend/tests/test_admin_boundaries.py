"""Integration tests for the admin-boundary hierarchy-browsing endpoints
(Select Area workflow), against real PostGIS and real JWT auth end to end.
Same ASGITransport pattern as test_villages.py.
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
from app.models.user import AppUser


async def _database_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _square_around(lon: float, lat: float, half_width: float = 0.01) -> Polygon:
    return Polygon(
        [
            (lon - half_width, lat - half_width),
            (lon + half_width, lat - half_width),
            (lon + half_width, lat + half_width),
            (lon - half_width, lat + half_width),
            (lon - half_width, lat - half_width),
        ]
    )


@pytest_asyncio.fixture
async def api_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def full_hierarchy():
    """A real State -> District -> Taluka -> Village chain, four levels
    deep, since Catchment.admin_boundary_id (and therefore this router's
    ancestor walk) may point at any of the four — not just village, the
    one depth reports.py's older alias-join pattern assumes."""
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    suffix = uuid4().hex[:8]
    state_name = f"TestState-{suffix}"
    district_name = f"TestDistrict-{suffix}"
    taluka_name = f"TestTaluka-{suffix}"
    village_name = f"TestVillage-{suffix}"

    async with AsyncSessionLocal() as db:
        state = AdminBoundary(
            level=BoundaryLevel.STATE, name=state_name, geometry=from_shape(_square_around(76.0, 18.0, 2.0), srid=4326)
        )
        db.add(state)
        await db.flush()

        district = AdminBoundary(
            level=BoundaryLevel.DISTRICT,
            name=district_name,
            parent_id=state.id,
            geometry=from_shape(_square_around(76.0, 18.0, 1.0), srid=4326),
        )
        db.add(district)
        await db.flush()

        taluka = AdminBoundary(
            level=BoundaryLevel.TALUKA,
            name=taluka_name,
            parent_id=district.id,
            geometry=from_shape(_square_around(76.0, 18.0, 0.3), srid=4326),
        )
        db.add(taluka)
        await db.flush()

        village = AdminBoundary(
            level=BoundaryLevel.VILLAGE,
            name=village_name,
            parent_id=taluka.id,
            geometry=from_shape(_square_around(76.0, 18.0), srid=4326),
        )
        db.add(village)
        await db.flush()

        # geometry_simplified is populated by load_admin_boundaries.py's
        # own follow-up UPDATE in real usage; the detail endpoint must
        # still work for a row where it's still NULL (fresh test data),
        # via its coalesce-to-geometry fallback.
        officer = AppUser(
            email=f"officer-{suffix}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
        )
        db.add(officer)
        await db.commit()

        for obj in (state, district, taluka, village, officer):
            await db.refresh(obj)

    yield {
        "state": state,
        "district": district,
        "taluka": taluka,
        "village": village,
        "officer": officer,
    }

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AdminBoundary).where(AdminBoundary.id.in_([village.id, taluka.id, district.id, state.id]))
        )
        await db.execute(delete(AppUser).where(AppUser.id == officer.id))
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str = "correct-password") -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_list_rejects_unauthenticated_request(api_client, full_hierarchy):
    response = await api_client.get("/api/v1/admin-boundaries")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_with_no_parent_id_returns_states(api_client, full_hierarchy):
    token = await _login(api_client, full_hierarchy["officer"].email)

    response = await api_client.get("/api/v1/admin-boundaries", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert str(full_hierarchy["state"].id) in rows
    assert rows[str(full_hierarchy["state"].id)]["level"] == "state"


@pytest.mark.asyncio
async def test_list_children_of_state_returns_only_its_districts(api_client, full_hierarchy):
    token = await _login(api_client, full_hierarchy["officer"].email)

    response = await api_client.get(
        "/api/v1/admin-boundaries",
        params={"parent_id": str(full_hierarchy["state"].id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    results = response.json()
    assert [row["id"] for row in results] == [str(full_hierarchy["district"].id)]
    assert results[0]["level"] == "district"


@pytest.mark.asyncio
async def test_list_children_cascades_down_to_villages(api_client, full_hierarchy):
    token = await _login(api_client, full_hierarchy["officer"].email)
    headers = {"Authorization": f"Bearer {token}"}

    districts = (
        await api_client.get(
            "/api/v1/admin-boundaries", params={"parent_id": str(full_hierarchy["state"].id)}, headers=headers
        )
    ).json()
    talukas = (
        await api_client.get(
            "/api/v1/admin-boundaries", params={"parent_id": districts[0]["id"]}, headers=headers
        )
    ).json()
    villages = (
        await api_client.get("/api/v1/admin-boundaries", params={"parent_id": talukas[0]["id"]}, headers=headers)
    ).json()

    assert [row["id"] for row in villages] == [str(full_hierarchy["village"].id)]
    assert villages[0]["level"] == "village"


@pytest.mark.asyncio
async def test_list_with_unknown_parent_returns_empty(api_client, full_hierarchy):
    token = await _login(api_client, full_hierarchy["officer"].email)

    response = await api_client.get(
        "/api/v1/admin-boundaries", params={"parent_id": str(uuid4())}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_detail_rejects_unauthenticated_request(api_client, full_hierarchy):
    response = await api_client.get(f"/api/v1/admin-boundaries/{full_hierarchy['village'].id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_detail_returns_404_for_unknown_id(api_client, full_hierarchy):
    token = await _login(api_client, full_hierarchy["officer"].email)

    response = await api_client.get(
        f"/api/v1/admin-boundaries/{uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_detail_for_village_resolves_full_ancestor_chain(api_client, full_hierarchy):
    token = await _login(api_client, full_hierarchy["officer"].email)

    response = await api_client.get(
        f"/api/v1/admin-boundaries/{full_hierarchy['village'].id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["level"] == "village"
    assert body["village"] == full_hierarchy["village"].name
    assert body["taluka"] == full_hierarchy["taluka"].name
    assert body["district"] == full_hierarchy["district"].name
    assert body["state"] == full_hierarchy["state"].name
    assert body["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert body["area_ha"] > 0


@pytest.mark.asyncio
async def test_detail_for_taluka_has_no_village_but_has_ancestors(api_client, full_hierarchy):
    """A catchment may be linked at taluka level, not just village — the
    schema comment on Catchment.admin_boundary_id says "village-level" as
    the common case, not the only one. The response must degrade sanely
    when self is above village."""
    token = await _login(api_client, full_hierarchy["officer"].email)

    response = await api_client.get(
        f"/api/v1/admin-boundaries/{full_hierarchy['taluka'].id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["level"] == "taluka"
    assert body["taluka"] == full_hierarchy["taluka"].name
    assert body["district"] == full_hierarchy["district"].name
    assert body["state"] == full_hierarchy["state"].name
    assert body["village"] is None


@pytest.mark.asyncio
async def test_detail_for_state_has_only_itself(api_client, full_hierarchy):
    token = await _login(api_client, full_hierarchy["officer"].email)

    response = await api_client.get(
        f"/api/v1/admin-boundaries/{full_hierarchy['state'].id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["level"] == "state"
    assert body["state"] == full_hierarchy["state"].name
    assert body["district"] is None
    assert body["taluka"] is None
    assert body["village"] is None
