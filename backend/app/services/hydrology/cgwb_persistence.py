"""CGWB observation persistence — upsert into `cgwb_groundwater_observation`
(ticket M3-004). Consumes `CgwbFetchResult` from `cgwb_ingest.py`; does not
fetch, parse, schedule, or expose anything over an API — those remain out
of scope, per this ticket's own instructions.

=====================================================================
DISCOVERED DISCREPANCY, FLAGGED AND RESOLVED — read before changing the
upsert identity below
=====================================================================

This ticket's own instructions describe upserting "using
(admin_boundary_id, assessment_year) as the unique identity." That
identity does not exist on the frozen schema. `CgwbGroundwaterObservation`
(app/models/cgwb.py, M0-006) has:
- no `admin_boundary_id` column or FK at all — deliberately: "one CGWB
  block observation spans many catchments, and the relationship is
  spatial... not a stored reference" (that model's own docstring). Adding
  one would be a schema change, explicitly forbidden by this ticket's own
  "Do NOT: Modify schemas" instruction.
- no `assessment_year` column — the real column is `assessment_period`,
  a `String(32)`, deliberately NOT a year/Date, because "CGWB's published
  period granularity isn't always a clean calendar year" (same
  docstring).

The table's actual, only unique identity is the existing
`uq_cgwb_block_period` constraint on `(block_code, assessment_period)` —
confirmed by reading the live model, not assumed. This module upserts
against THAT real identity. Associating an observation with an
`AdminBoundary` (and, through it, a catchment) remains the spatial-join
design already recommended in
docs/Water_Intelligence_CGWB_Ingestion_Design.md — a separate concern
from this ticket's persistence-identity requirement, and still not
implemented by any ticket to date.

=====================================================================
WHAT THIS MODULE DOES AND DOES NOT DO
=====================================================================

- Validates each `CgwbRawObservation` against the real column widths
  (`block_code`/`category` <= 64 chars, `assessment_period` <= 32 chars,
  `source_url` <= 2048 chars) before attempting to persist it — a second,
  independent validation layer beyond `cgwb_ingest.py`'s own parser-level
  checks (which only guarantee non-empty strings, not that they fit the
  destination columns).
- Records already reported as `CgwbRecordError` by the parser are
  counted as `skipped`, never re-validated or re-attempted here.
- `block_geometry` is left `None` (the column is nullable) — populating
  it requires the `AdminBoundary` spatial-matching step named above,
  which is not this ticket's scope.
- A genuine database-layer failure (not a per-record validation issue)
  rolls back the whole batch and re-raises — this ticket's own
  "Transaction rollback on DB failure" requirement is deliberately NOT
  folded into the `failed` counter: a per-record validation problem and
  a database outage are different failure classes, and silently
  swallowing the latter into a count would hide a real infrastructure
  problem from whoever calls this function.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cgwb import CgwbGroundwaterObservation
from app.services.hydrology.cgwb_ingest import CgwbFetchResult, CgwbRawObservation

logger = logging.getLogger(__name__)

# The real column widths from app/models/cgwb.py (M0-006) — checked here
# so a too-long value fails as a clean, counted `failed` record instead
# of an uncaught DB-level error surfacing mid-batch.
_BLOCK_CODE_MAX_LENGTH = 64
_CATEGORY_MAX_LENGTH = 64
_ASSESSMENT_PERIOD_MAX_LENGTH = 32
_SOURCE_URL_MAX_LENGTH = 2048


@dataclass(frozen=True)
class CgwbPersistenceSummary:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0


async def upsert_cgwb_observations(db: AsyncSession, fetch_result: CgwbFetchResult) -> CgwbPersistenceSummary:
    """Upsert every valid observation in `fetch_result` into
    `cgwb_groundwater_observation`, keyed on the table's real
    `(block_code, assessment_period)` uniqueness constraint (see module
    docstring for why this is not `(admin_boundary_id, assessment_year)`).

    - A `(block_code, assessment_period)` pair with no existing row is
      INSERTed.
    - A pair that exists with a DIFFERENT `category` is UPDATEd.
    - A pair that exists with the SAME `category` is a no-op, counted as
      `skipped` (this table's re-run-is-a-no-op idempotency guarantee,
      the same guarantee M0-006's own uniqueness-constraint test already
      proves at the database level).
    - Records already flagged by `cgwb_ingest.py`'s parser
      (`fetch_result.errors`) are counted as `skipped` without being
      touched here at all.
    - A record that passes the parser but fails THIS module's own
      column-width validation is counted as `failed`, not `skipped` —
      it reached persistence and was rejected here, a distinct failure
      class from "the parser already rejected it."

    One transaction for the whole batch: committed once at the end: if
    the database itself fails partway through (not a per-record
    validation issue), the whole batch is rolled back and the exception
    is re-raised — see module docstring.
    """
    skipped = len(fetch_result.errors)
    inserted = 0
    updated = 0
    failed = 0

    try:
        for observation in fetch_result.observations:
            validation_error = _validate_for_persistence(observation, fetch_result.source_url)
            if validation_error is not None:
                logger.warning(
                    "cgwb_persist_validation_failed",
                    extra={"block_code": observation.block_identifier, "reason": validation_error},
                )
                failed += 1
                continue

            outcome = await _upsert_one(db, observation, fetch_result.source_url)
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            else:
                skipped += 1

        await db.commit()
    except SQLAlchemyError:
        logger.error(
            "cgwb_persist_transaction_failed",
            extra={"inserted_so_far": inserted, "updated_so_far": updated},
        )
        await db.rollback()
        raise

    logger.info(
        "cgwb_persist_summary",
        extra={"inserted": inserted, "updated": updated, "skipped": skipped, "failed": failed},
    )
    return CgwbPersistenceSummary(inserted=inserted, updated=updated, skipped=skipped, failed=failed)


async def _upsert_one(db: AsyncSession, observation: CgwbRawObservation, source_url: str) -> str:
    """Returns "inserted", "updated", or "skipped" (no-op, value
    unchanged). Flushes (not commits) so the caller's single
    end-of-batch commit stays the actual transaction boundary."""
    existing = await db.scalar(
        select(CgwbGroundwaterObservation).where(
            CgwbGroundwaterObservation.block_code == observation.block_identifier,
            CgwbGroundwaterObservation.assessment_period == observation.assessment_period,
        )
    )

    if existing is None:
        db.add(
            CgwbGroundwaterObservation(
                block_code=observation.block_identifier,
                category=observation.category,
                assessment_period=observation.assessment_period,
                source_url=source_url,
            )
        )
        await db.flush()
        return "inserted"

    if existing.category != observation.category:
        existing.category = observation.category
        existing.source_url = source_url
        await db.flush()
        return "updated"

    return "skipped"


def _validate_for_persistence(observation: CgwbRawObservation, source_url: str) -> str | None:
    """Returns a human-readable reason string if the observation cannot
    be persisted as-is, else None. Distinct from cgwb_ingest.py's parser
    validation: that layer only guarantees non-empty strings; this layer
    checks the actual destination column widths, which the parser has no
    way to know about (it has no database dependency at all)."""
    if len(observation.block_identifier) > _BLOCK_CODE_MAX_LENGTH:
        return f"block_identifier exceeds {_BLOCK_CODE_MAX_LENGTH} characters"
    if len(observation.category) > _CATEGORY_MAX_LENGTH:
        return f"category exceeds {_CATEGORY_MAX_LENGTH} characters"
    if len(observation.assessment_period) > _ASSESSMENT_PERIOD_MAX_LENGTH:
        return f"assessment_period exceeds {_ASSESSMENT_PERIOD_MAX_LENGTH} characters"
    if not source_url or not source_url.strip():
        return "source_url is required and must be non-empty"
    if len(source_url) > _SOURCE_URL_MAX_LENGTH:
        return f"source_url exceeds {_SOURCE_URL_MAX_LENGTH} characters"
    return None
