from fastapi import FastAPI

from app.api.upload import router as upload_router
from app.api.district import router as district_router
from app.api.location import router as location_router

app = FastAPI(
    title="TerraRisk Credit Intelligence API",
    description="Climate Risk Intelligence Platform for Financial Institutions",
    version="0.1.0",
)

# Register API Routers
app.include_router(upload_router)
app.include_router(district_router)
app.include_router(location_router)


@app.get("/")
async def root():
    return {
        "application": "TerraRisk Credit Intelligence",
        "version": "0.1.0",
        "status": "running",
        "message": "Welcome to TerraRisk API"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }