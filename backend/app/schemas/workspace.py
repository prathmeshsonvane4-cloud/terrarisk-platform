"""Workspace list schemas (Product Design v2 §8 B1/B4 — M2B P7).

These power the workspace surfaces: Overview, Farms, Assessments, and
Reports indexes. Every item is a read-model over already-persisted rows —
no recomputation, no new writes. All lists are owner-or-branch scoped
server-side (the same rule as `user_can_access_owned_resource`, expressed
in SQL), so an unauthorized caller's list is simply shorter — ids never
leak through pagination totals either.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import JobStatus, RiskBand


class AssessmentSummary(BaseModel):
    """The latest completed assessment for a farm — enough for a list row;
    the full report stays behind GET /reports/{id}."""

    risk_score_id: UUID
    # Null when no composite could be estimated.
    overall_score: float | None
    overall_band: RiskBand | None
    # Legacy name: optical data completeness.
    confidence: float
    computed_at: datetime
    model_version: str


class ActiveJobSummary(BaseModel):
    job_id: UUID
    status: JobStatus
    created_at: datetime


class FarmListItem(BaseModel):
    id: UUID
    village_id: UUID
    village_name: str
    taluka_name: str
    district_name: str
    area_ha: float
    officer_name: str
    drawn_by: UUID
    created_at: datetime
    latest_assessment: AssessmentSummary | None
    active_job: ActiveJobSummary | None


class FarmListResponse(BaseModel):
    items: list[FarmListItem]
    total: int


class FarmAssessmentHistoryResponse(BaseModel):
    """Full assessment history for one farm, newest first, plus the
    in-flight run if any — the Farm detail timeline."""

    farm_id: UUID
    items: list[AssessmentSummary]
    active_job: ActiveJobSummary | None


class AssessmentListItem(BaseModel):
    """One farm-report run with its farm context resolved. Farm fields are
    nullable because a completed job's entity_id was overwritten with the
    risk-score id (P4 decision) — if that score's farm were ever deleted,
    the run row must still list rather than crash the index."""

    job_id: UUID
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    farm_id: UUID | None
    village_name: str | None
    area_ha: float | None
    officer_name: str
    risk_score_id: UUID | None
    overall_score: float | None
    overall_band: RiskBand | None
    error_message: str | None


class AssessmentListResponse(BaseModel):
    items: list[AssessmentListItem]
    total: int


class ReportListItem(BaseModel):
    risk_score_id: UUID
    farm_id: UUID
    village_name: str
    taluka_name: str
    district_name: str
    area_ha: float
    officer_name: str
    # Null when no composite could be estimated.
    overall_score: float | None
    overall_band: RiskBand | None
    # Legacy name: optical data completeness.
    confidence: float
    computed_at: datetime
    model_version: str


class ReportListResponse(BaseModel):
    items: list[ReportListItem]
    total: int
