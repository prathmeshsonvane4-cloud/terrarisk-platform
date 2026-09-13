"""Read lineage and validation for one result. Authorisation is the caller's
job — every endpoint using this checks access to the result first, with
the same guard its report endpoint already uses."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvidenceResultTable
from app.models.evidence import EvidenceRecord, ValidationRun
from app.schemas.evidence import EvidenceRecordResponse, ResultLineageResponse, ValidationRunResponse

__all__ = ["NOT_RECORDED_NOTE", "load_result_lineage"]

NOT_RECORDED_NOTE = (
    "Provenance not recorded: this result was computed before evidence lineage was persisted. "
    "Its inputs and parameters cannot be recovered from stored values, so none have been "
    "reconstructed."
)


async def load_result_lineage(
    db: AsyncSession, result_table: EvidenceResultTable, result_id: UUID
) -> ResultLineageResponse:
    evidence = (
        await db.execute(
            select(EvidenceRecord)
            .where(EvidenceRecord.result_table == result_table.value, EvidenceRecord.result_id == result_id)
            # Observations before parameters, then stable by name, so the
            # same result always reads back in the same order.
            .order_by(EvidenceRecord.kind.desc(), EvidenceRecord.quantity, EvidenceRecord.period_start)
        )
    ).scalars().all()
    runs = (
        await db.execute(
            select(ValidationRun)
            .where(ValidationRun.result_table == result_table.value, ValidationRun.result_id == result_id)
            .order_by(ValidationRun.created_at.desc())
        )
    ).scalars().all()

    return ResultLineageResponse(
        result_table=result_table.value,
        result_id=result_id,
        provenance_recorded=bool(evidence),
        provenance_note=None if evidence else NOT_RECORDED_NOTE,
        evidence=[EvidenceRecordResponse.model_validate(row) for row in evidence],
        validation_runs=[ValidationRunResponse.model_validate(run) for run in runs],
    )
