import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_root_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["application"] == "TerraRisk Credit Intelligence"


def test_routes_are_versioned_under_api_v1():
    schema = app.openapi()
    versioned_paths = [p for p in schema["paths"] if p not in ("/", "/health")]
    assert versioned_paths, "expected at least one versioned route"
    assert all(p.startswith("/api/v1/") for p in versioned_paths)


@pytest.mark.asyncio
async def test_locations_endpoint_no_longer_crashes_on_import():
    """Regression test for the broken `location.py` import found in the
    original repository audit (app.services.location_service.service did
    not exist — the real module is under app.services.climate_engine)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/v1/locations/states")
    assert response.status_code == 200
