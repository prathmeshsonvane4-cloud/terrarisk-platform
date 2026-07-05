from fastapi import APIRouter

from app.services.location_service.service import LocationService

router = APIRouter(prefix="/locations", tags=["Locations"])

location_service = LocationService()


@router.get("/states")
def get_states():
    return location_service.get_states()


@router.get("/districts")
def get_districts(state: str):
    return location_service.get_districts(state)