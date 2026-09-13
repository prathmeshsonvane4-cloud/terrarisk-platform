"""Write evidence and validation records into the caller's transaction.

Nothing here commits. Every function adds rows to the session it is given
and returns; the orchestrator commits once, after the result, its lineage
and its validation findings are all in the session. A result written
without its lineage — or lineage for a result that then failed to persist —
would be exactly the half-written state this layer exists to prevent.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvidenceResultTable
from app.models.evidence import EvidenceRecord, ValidationFinding, ValidationRun
from app.services.provenance.lineage import EvidenceItem
from app.services.validation import ValidationReport

__all__ = ["HARNESS_VERSION", "add_evidence", "add_validation_run"]

# Bump whenever a check, envelope, tolerance or zone rule in
# app/services/validation changes, so every persisted finding can be read
# against the rules that produced it. Format: year.month.revision.
HARNESS_VERSION = "2026.09.1"


def add_evidence(
    db: AsyncSession, result_table: EvidenceResultTable, result_id: UUID, items: list[EvidenceItem]
) -> list[EvidenceRecord]:
    rows = [
        EvidenceRecord(
            result_table=result_table.value,
            result_id=result_id,
            kind=item.kind.value,
            quantity=item.quantity,
            source=item.source,
            product_version=item.product_version,
            band=item.band,
            units=item.units,
            value=item.value,
            native_resolution_m=item.native_resolution_m,
            requested_scale_m=item.requested_scale_m,
            resampled=item.resampled,
            reducer=item.reducer,
            temporal_aggregation=item.temporal_aggregation,
            period_start=item.period_start,
            period_end=item.period_end,
            observations_expected=item.observations_expected,
            observations_used=item.observations_used,
            acquisition_dates=item.acquisition_dates,
            retrieval=item.retrieval,
            known_limitations=list(item.known_limitations),
            validation_status=item.validation_status.value,
            spec_verified_on=item.spec_verified_on,
        )
        for item in items
    ]
    db.add_all(rows)
    return rows


def add_validation_run(
    db: AsyncSession,
    result_table: EvidenceResultTable,
    result_id: UUID,
    report: ValidationReport,
    *,
    zone: str,
    source: str,
) -> ValidationRun:
    """Persist one validation pass and every finding in it — INFO findings
    included. A skipped check is recorded as an INFO finding, and dropping
    those would make a check that never ran indistinguishable from one that
    passed."""
    if source not in ("pipeline", "backfill"):
        raise ValueError(f"source must be 'pipeline' or 'backfill', got {source!r}")
    run = ValidationRun(
        result_table=result_table.value,
        result_id=result_id,
        harness_version=HARNESS_VERSION,
        agro_climatic_zone=zone,
        checks_run=report.checks_run,
        checks_skipped=report.checks_skipped,
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        failed=report.failed,
        source=source,
    )
    # Findings go through the relationship, never straight into the session:
    # that is what makes the unit of work insert the run first. See
    # ValidationRun.findings.
    run.findings = [
        ValidationFinding(
            check_name=finding.check,
            severity=finding.severity.value,
            subject=finding.subject[:160],
            observed=finding.observed,
            expected=finding.expected,
            message=finding.message,
            source=finding.source,
        )
        for finding in report.findings
    ]
    db.add(run)
    return run
