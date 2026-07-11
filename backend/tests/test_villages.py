"""Integration tests for the village search endpoint, against real PostGIS
and real JWT auth end to end. Uses httpx.AsyncClient + ASGITransport, same
pattern as test_farms.py/test_reports.py (see those files for why —
event-loop sharing with the module-level engine).
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
async def village_hierarchy():
    """A real district -> two talukas -> three villages hierarchy, with
    two villages deliberately sharing a name under different talukas —
    the exact real-data scenario (Blueprint §05, docs/DECISIONS.md M2A P1)
    the search endpoint's taluka/district disambiguation exists for."""
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")

    suffix = uuid4().hex[:8]
    district_name = f"TestDistrict-{suffix}"
    taluka_a_name = f"TestTalukaA-{suffix}"
    taluka_b_name = f"TestTalukaB-{suffix}"
    shared_name = f"TestVillageShared-{suffix}"
    unique_name = f"TestVillageUnique-{suffix}"

    async with AsyncSessionLocal() as db:
        district = AdminBoundary(
            level=BoundaryLevel.DISTRICT, name=district_name, geometry=from_shape(_square_around(76.0, 18.0, 1.0), srid=4326)
        )
        db.add(district)
        await db.flush()

        taluka_a = AdminBoundary(
            level=BoundaryLevel.TALUKA,
            name=taluka_a_name,
            parent_id=district.id,
            geometry=from_shape(_square_around(76.0, 18.0, 0.3), srid=4326),
        )
        taluka_b = AdminBoundary(
            level=BoundaryLevel.TALUKA,
            name=taluka_b_name,
            parent_id=district.id,
            geometry=from_shape(_square_around(76.5, 18.5, 0.3), srid=4326),
        )
        db.add_all([taluka_a, taluka_b])
        await db.flush()

        village_in_a = AdminBoundary(
            level=BoundaryLevel.VILLAGE,
            name=shared_name,
            parent_id=taluka_a.id,
            geometry=from_shape(_square_around(76.0, 18.0), srid=4326),
        )
        village_in_b = AdminBoundary(
            level=BoundaryLevel.VILLAGE,
            name=shared_name,
            parent_id=taluka_b.id,
            geometry=from_shape(_square_around(76.5, 18.5), srid=4326),
        )
        village_unique = AdminBoundary(
            level=BoundaryLevel.VILLAGE,
            name=unique_name,
            parent_id=taluka_a.id,
            geometry=from_shape(_square_around(76.1, 18.1), srid=4326),
        )
        db.add_all([village_in_a, village_in_b, village_unique])

        officer = AppUser(
            email=f"officer-{suffix}@example.com",
            password_hash=hash_password("correct-password"),
            full_name="Test Officer",
            role=UserRole.CREDIT_OFFICER,
            is_active=True,
        )
        db.add(officer)
        await db.commit()

        for obj in (district, taluka_a, taluka_b, village_in_a, village_in_b, village_unique, officer):
            await db.refresh(obj)

    yield {
        "district": district,
        "taluka_a": taluka_a,
        "taluka_b": taluka_b,
        "village_in_a": village_in_a,
        "village_in_b": village_in_b,
        "village_unique": village_unique,
        "officer": officer,
        "shared_name": shared_name,
        "unique_name": unique_name,
    }

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AdminBoundary).where(
                AdminBoundary.id.in_(
                    [village_in_a.id, village_in_b.id, village_unique.id, taluka_a.id, taluka_b.id, district.id]
                )
            )
        )
        await db.execute(delete(AppUser).where(AppUser.id == officer.id))
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str = "correct-password") -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_search_rejects_unauthenticated_request(api_client, village_hierarchy):
    response = await api_client.get("/api/v1/villages", params={"q": village_hierarchy["unique_name"]})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_search_matches_by_partial_case_insensitive_name(api_client, village_hierarchy):
    token = await _login(api_client, village_hierarchy["officer"].email)
    partial_query = village_hierarchy["unique_name"][:-4].lower()  # drop the last few chars, lowercase

    response = await api_client.get(
        "/api/v1/villages", params={"q": partial_query}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    names = [row["name"] for row in response.json()]
    assert village_hierarchy["unique_name"] in names


@pytest.mark.asyncio
async def test_search_returns_taluka_and_district_and_centroid(api_client, village_hierarchy):
    token = await _login(api_client, village_hierarchy["officer"].email)

    response = await api_client.get(
        "/api/v1/villages", params={"q": village_hierarchy["unique_name"]}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    [result] = response.json()
    assert result["taluka"] == village_hierarchy["taluka_a"].name
    assert result["district"] == village_hierarchy["district"].name
    assert -90 <= result["centroid"]["lat"] <= 90
    assert -180 <= result["centroid"]["lon"] <= 180


@pytest.mark.asyncio
async def test_search_disambiguates_same_village_name_across_talukas(api_client, village_hierarchy):
    """The real-data scenario this endpoint's taluka field exists for
    (docs/DECISIONS.md, M2A P1) — two distinct villages, same name,
    different taluka, must both come back as separate rows."""
    token = await _login(api_client, village_hierarchy["officer"].email)

    response = await api_client.get(
        "/api/v1/villages", params={"q": village_hierarchy["shared_name"]}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    results = response.json()
    matching = [r for r in results if r["name"] == village_hierarchy["shared_name"]]
    assert len(matching) == 2
    talukas = {r["taluka"] for r in matching}
    assert talukas == {village_hierarchy["taluka_a"].name, village_hierarchy["taluka_b"].name}


@pytest.mark.asyncio
async def test_search_below_minimum_length_returns_empty_without_querying(api_client, village_hierarchy):
    token = await _login(api_client, village_hierarchy["officer"].email)

    response = await api_client.get("/api/v1/villages", params={"q": "a"}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_with_no_matches_returns_empty_list(api_client, village_hierarchy):
    token = await _login(api_client, village_hierarchy["officer"].email)

    response = await api_client.get(
        "/api/v1/villages", params={"q": "Zzzznonexistentvillagequery"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json() == []
