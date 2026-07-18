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


@pytest.mark.asyncio
async def test_health_ready_endpoint_reports_component_checks():
    """/health/ready (M3) checks real dependencies (DB, GEE config), so its
    overall status legitimately varies with the environment this test runs
    in (a live PostGIS may or may not be reachable, GEE credentials may or
    may not be configured) — unlike /health, this test asserts the response
    *shape* and that it never raises, not one fixed status."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/health/ready")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in ("ok", "degraded")
    assert set(body["checks"]) == {"database", "earth_engine"}
    assert body["checks"]["database"]["status"] in ("ok", "error")
    assert body["checks"]["earth_engine"]["status"] in ("configured", "misconfigured", "not_configured")


def test_routes_are_versioned_under_api_v1():
    schema = app.openapi()
    top_level_paths = {"/", "/health", "/health/ready"}
    versioned_paths = [p for p in schema["paths"] if p not in top_level_paths]
    assert versioned_paths, "expected at least one versioned route"
    assert all(p.startswith("/api/v1/") for p in versioned_paths)
