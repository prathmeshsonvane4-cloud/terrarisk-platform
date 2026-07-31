"""Water report read schemas (Water Intelligence, ticket M5-003) —
`GET /catchments/{id}/water-reports`' only response shape.

A new file, not an addition to `app/schemas/catchment.py` or
`app/schemas/report.py`: this ticket's own "Do NOT: Modify schemas" is
read here as "don't touch any schema class another ticket already
froze" — `CatchmentResponse`, `ReportResponse`, `JobStatusResponse`, etc.
are all unmodified by this file. A response combining
`WaterBalanceResult` + `RechargeStressScore` + Job metadata + a generated
timestamp does not exist anywhere yet — this is the first ticket to
expose either result row over the API at all — so a purely additive new
file is the only way to satisfy this ticket's own stated Goal without
touching anything frozen.

Job metadata specifically reuses `JobStatusResponse`
(`app/schemas/job.py`) as-is rather than re-declaring an equivalent
shape — the literal "reuse existing" this ticket asks for.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import BaselineWindow, CalibrationStatus, StorageChangeBand, StressBand
from app.schemas.job import JobStatusResponse


class WaterBalanceResultResponse(BaseModel):
    """Field-for-field mirror of `app.models.water_balance.WaterBalanceResult`
    (see that model for the full column-by-column rationale) — no
    catchment_id (redundant with the parent response's own field)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period_start: date
    period_end: date
    rainfall_mm: float | None
    et_mm: float | None
    runoff_mm: float | None
    storage_change_mm: float | None
    storage_change_band: StorageChangeBand
    data_completeness: float
    calibration_status: CalibrationStatus
    closed_catchment_assumed: bool
    resolution_flags: list[str]
    model_version: str
    computed_at: datetime


class RechargeStressScoreResponse(BaseModel):
    """Field-for-field mirror of `app.models.water_balance.RechargeStressScore`
    — `weights_version_id` deliberately excluded: it is always `None`
    today (see `water_report_generator.py`'s own architecture-decision
    docstring, point 3 — no ConfigWeight row exists for this factor set
    yet), so exposing it would only ever show a client a field that
    never has a value."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stress_score: float
    stress_band: StressBand
    baseline_window: BaselineWindow
    rainfall_anomaly_ratio: float | None
    vci: float | None
    surface_water_trend: float | None
    cgwb_category: str | None
    cgwb_category_as_of: date | None
    raw_inputs: dict
    computed_at: datetime


class WaterReportHistoryItem(BaseModel):
    """One past completed run for a catchment — the same
    `WaterBalanceResult` + `RechargeStressScore` sibling pair
    `WaterReportDetailResponse` carries for the latest run, without the
    `job` field (a history list has no use for re-fetching job/progress
    metadata for runs that finished long ago). Powers both the
    per-catchment trend view and multi-catchment comparison
    (docs/WELL_Labs_Raichur_Founder_Review_2026.md Part 4/5) — one shape,
    two frontend presentations, since both are just "several of these,
    read together" rather than distinct data needs.
    """

    generated_at: datetime
    water_balance: WaterBalanceResultResponse
    recharge_stress: RechargeStressScoreResponse


class WaterReportDetailResponse(BaseModel):
    """`GET /catchments/{id}/water-reports`' full response — the latest
    completed run's `WaterBalanceResult` + `RechargeStressScore`
    siblings, the `Job` that produced them, and a single `generated_at`
    timestamp: the shared `computed_at` both result rows are stamped
    with in the same orchestrator run (`water_report_generator.py`
    computes it once and passes it to both), not a third, independently
    meaningful value.
    """

    catchment_id: UUID
    generated_at: datetime
    water_balance: WaterBalanceResultResponse
    recharge_stress: RechargeStressScoreResponse
    job: JobStatusResponse
