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
    # The real Sentinel-2 acquisition dates that fed this month's composite
    # (M2B P9 Evidence tab). Always empty for rainfall — CHIRPS is a daily
    # gridded product with no discrete "scene" concept, never fabricated
    # dates standing in for one.
    source_dates: list[date] = Field(default_factory=list)


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


class ReportEvidenceContext(BaseModel):
    """Answers 'which observations contributed' (M2B P9 Evidence tab).
    Both fields are the exact (start, end) _run_pipeline actually queried
    Earth Engine with — persisted at compute time (RiskScore.observation_
    window_start/end), never re-derived. None for reports computed before
    this column existed; the frontend shows the rest of the report
    normally and simply omits window-dependent Evidence detail."""

    observation_window_start: date | None
    observation_window_end: date | None
    # Calendar months in [window_start, window_end) — the same
    # _monthly_periods() the pipeline itself used, so this can never drift
    # from what a given report actually expected to observe.
    expected_months: int | None


class ReportMethodContext(BaseModel):
    """Answers 'why this score' (M2B P9 Method tab) — the versioned
    weights and floor rule actually applied, read back from config_weight
    via risk_score.weights_version_id. Never recomputed: RiskEngine.compute()
    is the only place factor-to-composite arithmetic happens; this is a
    read-only reflection of its already-persisted inputs and output."""

    weights_version_id: UUID
    weights: dict[str, float]
    weights_effective_from: datetime
    floor_threshold: float
    # The plain weighted average before the floor rule could raise it —
    # None only for legacy rows computed before this column existed.
    # When present and different from overall_score, the floor rule fired.
    weighted_average_score: float | None


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
    # M2B P9 additive enrichment — Evidence & Method tabs read this same
    # payload; no second endpoint, no recomputation.
    evidence: ReportEvidenceContext
    method: ReportMethodContext
