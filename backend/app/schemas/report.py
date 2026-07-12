from datetime import date, datetime
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


class ObservationPoint(BaseModel):
    """One monthly composited value from the satellite_observation cache —
    real persisted data from the generation run, never recomputed at read
    time (Blueprint §03: report reads never trigger a live GEE call)."""

    period_start: date
    value: float


class ReportSeries(BaseModel):
    """The monthly series the dashboard charts (M2A P5). All four cached
    index types are included even though the M2A dashboard charts only
    NDVI and rainfall — MNDWI/NDMI back the M2B factor drill-downs with
    no further payload change. A month missing from a list was
    unobservable (cloud-blanked or not yet published), never zero."""

    ndvi: list[ObservationPoint]
    mndwi: list[ObservationPoint]
    ndmi: list[ObservationPoint]
    rainfall: list[ObservationPoint]


class ReportFarmContext(BaseModel):
    """Farm identity block for the report header and map panel (Blueprint
    §08 "Farm information": provenance for anything entering a bank's
    file)."""

    geometry: dict  # GeoJSON of the officer-drawn boundary (WGS84)
    village_name: str
    taluka_name: str
    district_name: str
    officer_name: str


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
    # M2A P5 additive enrichment — same single payload powers the
    # dashboard and (P6) the PDF, per Blueprint §08's one-artifact rule.
    farm: ReportFarmContext
    series: ReportSeries
