import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.farms import router as farms_router
from app.api.jobs import router as jobs_router
from app.api.reports import router as reports_router
from app.api.villages import router as villages_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.base import AsyncSessionLocal

settings = get_settings()
configure_logging(level="DEBUG" if settings.debug else "INFO")
logger = logging.getLogger(__name__)
logger.info(
    "application_startup",
    extra={"app_name": settings.app_name, "app_version": settings.app_version, "environment": settings.environment},
)

app = FastAPI(
    title="TerraRisk Credit Intelligence API",
    description="Climate Risk Intelligence Platform for Financial Institutions",
    version="0.1.0",
)

# M2A: the Next.js frontend is a separate origin. A single explicit origin,
# never a wildcard — requests carry a bearer token in the Authorization
# header, and allow_credentials is left False since the token travels in a
# header, not a cookie, so no cross-site cookie exposure is possible either way.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Versioned from the first endpoint (Blueprint §03 / CTO review finding):
# free to enforce now, a breaking change to retrofit once anything external
# depends on an unversioned URL.
API_V1_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_V1_PREFIX)
app.include_router(villages_router, prefix=API_V1_PREFIX)
app.include_router(farms_router, prefix=API_V1_PREFIX)
app.include_router(jobs_router, prefix=API_V1_PREFIX)
app.include_router(reports_router, prefix=API_V1_PREFIX)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Single error envelope (Blueprint §03) — every failure response has
    the same {"error": {"code", "message", ...}} shape, regardless of
    endpoint. `detail` is normally a plain string; a handful of call sites
    (e.g. the 409 on a duplicate in-flight report — M2B P7 B5) need to
    carry one extra structured field (job_id) so the client can route
    straight to it instead of just reading an error string. Passing a dict
    detail with a "message" key adds that field to the envelope without
    changing the shape any existing caller relies on.
    """
    if isinstance(exc.detail, dict):
        message = exc.detail.get("message", "")
        extra = {k: v for k, v in exc.detail.items() if k != "message"}
    else:
        message, extra = exc.detail, {}
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": message, **extra}},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catches anything that isn't a deliberately-raised HTTPException —
    without this, an unexpected error falls through to FastAPI's default
    handling, which can leak internal exception detail to the client. Full
    detail goes to the server log only; the response is always generic."""
    logger.exception("unhandled_exception", extra={"path": request.url.path, "method": request.method})
    return JSONResponse(
        status_code=500,
        content={"error": {"code": 500, "message": "An internal error occurred. Please try again later."}},
    )


@app.get("/")
async def root():
    return {
        "application": "TerraRisk Credit Intelligence",
        "version": "0.1.0",
        "status": "running",
        "message": "Welcome to TerraRisk API",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    """Deployment readiness probe (M3) — distinct from /health, which is a
    cheap liveness check with no dependencies and stays unchanged (asserted
    verbatim by tests/test_health.py). This one actually verifies the
    things a fresh deployment can get wrong: DB connectivity, and whether
    Earth Engine credentials are configured.

    Earth Engine's check is deliberately config/credential-file presence,
    not a live ee.Initialize() call — actually initializing here would mean
    a real network round-trip (and, per GeeProvider's own design, a
    thread-pool hop — see docs/DECISIONS.md) on every orchestrator probe
    hit, which is impractical to do on a health-check cadence, not just
    undesirable. Container/compose healthchecks target the cheap /health,
    not this endpoint, for the same reason.
    """
    checks: dict[str, dict] = {}

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 — any DB failure means "not ready", not a 500
        checks["database"] = {"status": "error", "detail": str(exc)}

    gee_configured = bool(settings.gee_project_id and settings.gee_service_account_json_path)
    gee_key_present = gee_configured and Path(settings.gee_service_account_json_path).is_file()
    if gee_configured and gee_key_present:
        checks["earth_engine"] = {"status": "configured"}
    elif gee_configured:
        checks["earth_engine"] = {"status": "misconfigured", "detail": "service account key file not found on disk"}
    else:
        checks["earth_engine"] = {"status": "not_configured"}

    overall_ok = checks["database"]["status"] == "ok" and checks["earth_engine"]["status"] == "configured"
    return JSONResponse(
        status_code=200 if overall_ok else 503,
        content={"status": "ok" if overall_ok else "degraded", "checks": checks},
    )
