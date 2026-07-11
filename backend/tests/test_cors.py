"""Regression test for the M2A CORS policy (app/main.py): the frontend's
origin must be allowed, and only that origin — no wildcard, since requests
carry a bearer token in the Authorization header."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app


@pytest.mark.asyncio
async def test_preflight_allows_the_configured_frontend_origin():
    frontend_origin = get_settings().frontend_origin
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": frontend_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == frontend_origin


@pytest.mark.asyncio
async def test_preflight_rejects_an_unrecognized_origin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
    # Starlette's CORSMiddleware answers a disallowed-origin preflight with
    # 200 but omits Access-Control-Allow-Origin — the browser enforces the
    # actual block client-side, so the absence of the header is the check.
    assert "access-control-allow-origin" not in response.headers
