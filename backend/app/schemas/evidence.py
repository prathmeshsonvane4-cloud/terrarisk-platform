"""Response shapes for evidence lineage and validation (Phase B, item 5).

Read-only views of `evidence_record`, `validation_run` and
`validation_finding`. Rendering lineage in the report itself is deliberately
not done here — the report's output changes in the confidence, sufficiency
and decision work that follows, and building that UI twice would be waste.
These endpoints make every persisted lineage row retrievable now.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EvidenceRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    quantity: str
    source: str
    product_version: str | None
    band: str | None
    units: str
    value: float | None
    native_resolution_m: float | None
    requested_scale_m: float | None
    resampled: bool | None
    reducer: str | None
    temporal_aggregation: str | None
    period_start: date | None
    period_end: date | None
    observations_expected: int | None
    observations_used: int | None
    # null = not recorded; [] = recorded, none. The distinction is
    # deliberate and must survive serialisation.
    acquisition_dates: list[str] | None
    retrieval: str | None
    known_limitations: list[str]
    validation_status: str
    spec_verified_on: date | None


class ValidationFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    check_name: str
    severity: str
    subject: str
    observed: float | None
    expected: str
    message: str
    source: str


class ValidationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    harness_version: str
    agro_climatic_zone: str
    checks_run: int
    checks_skipped: int
    error_count: int
    warning_count: int
    failed: bool
    source: str
    created_at: datetime
    findings: list[ValidationFindingResponse]


class ResultLineageResponse(BaseModel):
    """Lineage and validation for one result row.

    `provenance_recorded` is False for any result computed before lineage
    was persisted. Those results get NO reconstructed evidence — the
    parameters they were computed with cannot be recovered — and the note
    says so plainly rather than the list simply being empty.
    """

    result_table: str
    result_id: UUID
    provenance_recorded: bool
    provenance_note: str | None
    evidence: list[EvidenceRecordResponse]
    validation_runs: list[ValidationRunResponse]


class WaterReportLineageResponse(BaseModel):
    catchment_id: UUID
    water_balance: ResultLineageResponse
    recharge_stress: ResultLineageResponse
