"""Tests for CGWB observation persistence (ticket M3-004).

Split like tests/test_cgwb_model.py: pure/mock-session tests for
control-flow (the transaction-rollback behavior), which always run; and
live-Postgres tests for actual insert/update/no-op persistence
correctness, which skip cleanly without Docker/PostGIS — mirroring that
file's exact `_database_reachable()`/`db_session` pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.database.base import AsyncSessionLocal, engine
from app.models.cgwb import CgwbGroundwaterObservation
from app.services.hydrology.cgwb_ingest import (
    CgwbFetchMetadata,
    CgwbFetchResult,
    CgwbRawObservation,
    CgwbRecordError,
)
from app.services.hydrology.cgwb_persistence import upsert_cgwb_observations

_SOURCE_URL = "https://example.gov.in/backend/dataapi/v1/resource/test-fixture"


def _metadata(total: int = 0) -> CgwbFetchMetadata:
    return CgwbFetchMetadata(title="Test", total=total, count=total, limit=100, offset=0, updated_at=None)


def _observation(
    block_identifier: str | None = None,
    category: str = "Safe",
    assessment_period: str = "2024",
) -> CgwbRawObservation:
    return CgwbRawObservation(
        block_identifier=block_identifier or f"TEST-BLOCK-{uuid4().hex[:8]}",
        category=category,
        assessment_period=assessment_period,
        state=None,
        raw={},
    )


def _fetch_result(
    observations: list[CgwbRawObservation] | None = None,
    errors: list[CgwbRecordError] | None = None,
    source_url: str = _SOURCE_URL,
) -> CgwbFetchResult:
    observations = observations if observations is not None else []
    return CgwbFetchResult(
        metadata=_metadata(len(observations)),
        observations=observations,
        source_url=source_url,
        errors=errors or [],
    )


def _mock_session() -> AsyncMock:
    """A mock AsyncSession with `.add` overridden to a plain (non-async)
    Mock — the real AsyncSession.add() is synchronous even on an async
    session (only flush/commit/rollback/scalar are awaited); a bare
    AsyncMock() mocks every attribute as async by default, which would
    leave `db.add(...)` an unawaited coroutine and trigger spurious
    RuntimeWarnings unrelated to any real bug in the code under test."""
    session = AsyncMock()
    session.add = Mock()
    return session


async def _database_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def db_session():
    if not await _database_reachable():
        pytest.skip("local PostGIS not reachable — start docker/docker-compose.yml")
    async with AsyncSessionLocal() as session:
        yield session


class TestTransactionRollbackOnDbFailure:
    """Pure control-flow test against a mock AsyncSession — no real
    database needed, always runs. Proves the function rolls back and
    re-raises rather than silently swallowing a genuine database
    failure into the `failed` counter (see module docstring for why
    those are treated as different failure classes)."""

    async def test_commit_failure_triggers_rollback_and_reraises(self):
        db = _mock_session()
        db.scalar = AsyncMock(return_value=None)  # no existing row -> insert path
        db.commit = AsyncMock(side_effect=SQLAlchemyError("simulated connection loss"))

        fetch_result = _fetch_result(observations=[_observation()])

        with pytest.raises(SQLAlchemyError, match="simulated connection loss"):
            await upsert_cgwb_observations(db, fetch_result)

        db.rollback.assert_awaited_once()

    async def test_flush_failure_during_insert_triggers_rollback_and_reraises(self):
        db = _mock_session()
        db.scalar = AsyncMock(return_value=None)
        db.flush = AsyncMock(side_effect=SQLAlchemyError("simulated constraint violation"))

        fetch_result = _fetch_result(observations=[_observation()])

        with pytest.raises(SQLAlchemyError, match="simulated constraint violation"):
            await upsert_cgwb_observations(db, fetch_result)

        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()  # never reached commit


class TestEmptyBatch:
    """Pure — an empty batch needs no database at all to prove it's a
    clean no-op."""

    async def test_empty_batch_returns_all_zero_counts(self):
        db = _mock_session()
        result = await upsert_cgwb_observations(db, _fetch_result(observations=[], errors=[]))

        assert result.inserted == 0
        assert result.updated == 0
        assert result.skipped == 0
        assert result.failed == 0
        db.commit.assert_awaited_once()  # still commits — an empty batch is a valid, successful run

    async def test_errors_only_batch_counts_as_skipped_without_touching_the_database(self):
        db = _mock_session()
        fetch_result = _fetch_result(
            observations=[],
            errors=[CgwbRecordError(reason="missing category", raw={})],
        )

        result = await upsert_cgwb_observations(db, fetch_result)

        assert result.skipped == 1
        assert result.inserted == 0
        db.scalar.assert_not_called()  # no observation ever reached the DB layer


class TestInvalidRecordHandling:
    """Pure — column-width validation needs no database, since a record
    this module rejects is never queried against one."""

    async def test_block_identifier_too_long_is_counted_as_failed_not_skipped(self):
        db = _mock_session()
        too_long = "X" * 65  # column is String(64)
        fetch_result = _fetch_result(observations=[_observation(block_identifier=too_long)])

        result = await upsert_cgwb_observations(db, fetch_result)

        assert result.failed == 1
        assert result.skipped == 0  # distinct from parser-flagged skips
        db.scalar.assert_not_called()

    async def test_category_too_long_is_counted_as_failed(self):
        db = _mock_session()
        fetch_result = _fetch_result(observations=[_observation(category="X" * 65)])
        result = await upsert_cgwb_observations(db, fetch_result)
        assert result.failed == 1

    async def test_assessment_period_too_long_is_counted_as_failed(self):
        db = _mock_session()
        fetch_result = _fetch_result(observations=[_observation(assessment_period="X" * 33)])
        result = await upsert_cgwb_observations(db, fetch_result)
        assert result.failed == 1

    async def test_empty_source_url_is_counted_as_failed(self):
        db = _mock_session()
        fetch_result = _fetch_result(observations=[_observation()], source_url="")
        result = await upsert_cgwb_observations(db, fetch_result)
        assert result.failed == 1

    async def test_one_invalid_record_does_not_block_a_valid_one_in_the_same_batch(self):
        db = _mock_session()
        db.scalar = AsyncMock(return_value=None)
        fetch_result = _fetch_result(
            observations=[_observation(block_identifier="X" * 65), _observation()]
        )

        result = await upsert_cgwb_observations(db, fetch_result)

        assert result.failed == 1
        assert result.inserted == 1


class TestInsertUpdateAndDuplicateHandling:
    """Live-Postgres tests — real insert/update/no-op correctness against
    the actual `uq_cgwb_block_period` constraint, mirroring
    test_cgwb_model.py's exact skip-cleanly-without-Docker convention."""

    async def test_new_observation_is_inserted(self, db_session):
        block_code = f"TEST-BLOCK-{uuid4().hex[:8]}"
        fetch_result = _fetch_result(observations=[_observation(block_identifier=block_code, category="Safe")])

        result = await upsert_cgwb_observations(db_session, fetch_result)

        assert result.inserted == 1
        assert result.updated == 0
        assert result.skipped == 0
        assert result.failed == 0

        row = await db_session.scalar(
            select(CgwbGroundwaterObservation).where(CgwbGroundwaterObservation.block_code == block_code)
        )
        assert row is not None
        assert row.category == "Safe"
        assert row.assessment_period == "2024"
        assert row.source_url == _SOURCE_URL
        assert row.block_geometry is None  # not populated by this ticket — see module docstring

    async def test_existing_observation_with_a_changed_category_is_updated(self, db_session):
        block_code = f"TEST-BLOCK-{uuid4().hex[:8]}"
        first_run = _fetch_result(observations=[_observation(block_identifier=block_code, category="Safe")])
        await upsert_cgwb_observations(db_session, first_run)

        second_run = _fetch_result(observations=[_observation(block_identifier=block_code, category="Critical")])
        result = await upsert_cgwb_observations(db_session, second_run)

        assert result.updated == 1
        assert result.inserted == 0

        row = await db_session.scalar(
            select(CgwbGroundwaterObservation).where(CgwbGroundwaterObservation.block_code == block_code)
        )
        assert row.category == "Critical"

    async def test_existing_observation_with_an_unchanged_category_is_skipped_not_updated(self, db_session):
        block_code = f"TEST-BLOCK-{uuid4().hex[:8]}"
        first_run = _fetch_result(observations=[_observation(block_identifier=block_code, category="Safe")])
        await upsert_cgwb_observations(db_session, first_run)

        second_run = _fetch_result(observations=[_observation(block_identifier=block_code, category="Safe")])
        result = await upsert_cgwb_observations(db_session, second_run)

        assert result.skipped == 1
        assert result.updated == 0
        assert result.inserted == 0

    async def test_rerunning_the_same_batch_twice_is_fully_idempotent(self, db_session):
        """The exact re-run-is-a-no-op guarantee this table's uniqueness
        constraint exists for (M0-006's own stated purpose)."""
        block_code = f"TEST-BLOCK-{uuid4().hex[:8]}"
        fetch_result = _fetch_result(observations=[_observation(block_identifier=block_code, category="Semi-Critical")])

        first = await upsert_cgwb_observations(db_session, fetch_result)
        second = await upsert_cgwb_observations(db_session, fetch_result)

        assert first.inserted == 1
        assert second.inserted == 0
        assert second.skipped == 1

        count = await db_session.scalar(
            select(CgwbGroundwaterObservation).where(CgwbGroundwaterObservation.block_code == block_code)
        )
        assert count is not None  # exactly one row exists — no duplicate was ever attempted

    async def test_same_block_different_assessment_period_is_a_separate_insert(self, db_session):
        block_code = f"TEST-BLOCK-{uuid4().hex[:8]}"
        await upsert_cgwb_observations(
            db_session, _fetch_result(observations=[_observation(block_identifier=block_code, assessment_period="2023")])
        )
        result = await upsert_cgwb_observations(
            db_session, _fetch_result(observations=[_observation(block_identifier=block_code, assessment_period="2024")])
        )

        assert result.inserted == 1  # a new period for the same block is a new row, not an update

    async def test_the_real_unique_constraint_still_rejects_a_direct_raw_duplicate_insert(self, db_session):
        """Sanity check this module's identity choice against the real
        constraint directly (bypassing the upsert function) — confirms
        (block_code, assessment_period) is genuinely still the
        database's own enforced identity, not just this module's
        assumption about it."""
        block_code = f"TEST-BLOCK-{uuid4().hex[:8]}"
        db_session.add(
            CgwbGroundwaterObservation(
                block_code=block_code, category="Safe", assessment_period="2024", source_url=_SOURCE_URL
            )
        )
        await db_session.commit()

        db_session.add(
            CgwbGroundwaterObservation(
                block_code=block_code, category="Critical", assessment_period="2024", source_url=_SOURCE_URL
            )
        )
        with pytest.raises(IntegrityError, match="uq_cgwb_block_period"):
            await db_session.commit()
        await db_session.rollback()
