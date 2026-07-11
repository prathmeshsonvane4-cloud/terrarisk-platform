import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.farms import router as farms_router
from app.api.jobs import router as jobs_router
from app.api.reports import router as reports_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging(level="DEBUG" if get_settings().debug else "INFO")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TerraRisk Credit Intelligence API",
    description="Climate Risk Intelligence Platform for Financial Institutions",
    version="0.1.0",
)

# Versioned from the first endpoint (Blueprint §03 / CTO review finding):
# free to enforce now, a breaking change to retrofit once anything external
# depends on an unversioned URL.
API_V1_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_V1_PREFIX)
app.include_router(farms_router, prefix=API_V1_PREFIX)
app.include_router(jobs_router, prefix=API_V1_PREFIX)
app.include_router(reports_router, prefix=API_V1_PREFIX)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Single error envelope (Blueprint §03) — every failure response has
    the same {"error": {"code", "message"}} shape, regardless of endpoint."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail}},
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
