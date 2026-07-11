from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RiskBand, RiskFactor


class ReportGenerateRequest(BaseModel):
    lookback_years: int = Field(default=3, ge=1, le=10)


class ReportTriggerResponse(BaseModel):
    job_id: UUID
    status: str = "queued"


class FactorScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    factor: RiskFactor
    value: float
    band: RiskBand
    raw_inputs: dict


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    farm_area_ha: float
    village_id: UUID
    overall_score: float
    overall_band: RiskBand
    confidence: float
    model_version: str
    computed_at: datetime
    factors: list[FactorScoreResponse]
