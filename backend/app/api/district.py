from fastapi import APIRouter

from app.services.climate_engine.engine import ClimateEngine

router = APIRouter(prefix="/district", tags=["District"])

engine = ClimateEngine()


@router.get("/report")
def generate_report(state: str, district: str):
    return engine.generate_district_report(state, district)