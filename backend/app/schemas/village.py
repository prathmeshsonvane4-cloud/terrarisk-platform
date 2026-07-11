from uuid import UUID

from pydantic import BaseModel


class VillageCentroid(BaseModel):
    lat: float
    lon: float


class VillageSearchResult(BaseModel):
    id: UUID
    name: str
    taluka: str
    district: str
    centroid: VillageCentroid
