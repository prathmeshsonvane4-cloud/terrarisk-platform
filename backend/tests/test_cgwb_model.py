"""Integration test for CgwbGroundwaterObservation's uq_cgwb_block_period
uniqueness constraint, against a real local PostGIS instance — the same
"offline compile proves the constraint exists, live Postgres proves it's
enforced" split already established in tests/test_catchment_model.py
(M0-003), mirrored here exactly.

This is the specific test ticket M0-006 requires: proof that a duplicate
(block_code, assessment_period) pair is rejected, not just documented as
rejected — the exact mechanism M3's future ingestion job will rely on for
idempotent re-runs.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database.base import AsyncSessionLocal, engine
from app.models.cgwb import CgwbGroundwaterObservation


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


async def test_valid_observation_persists(db_session):
    """Sanity check the constraint isn't accidentally rejecting legitimate
    data — no block_geometry needed, since it's nullable until M3."""
    observation = CgwbGroundwaterObservation(
        block_code=f"TEST-BLOCK-{uuid4().hex[:8]}",
        category="safe",
        assessment_period="2024",
        source_url="https://indiawris.gov.in/wris/example",
    )
    db_session.add(observation)
    await db_session.commit()
    await db_session.refresh(observation)
    assert observation.id is not None
    assert observation.ingested_at is not None


async def test_duplicate_block_code_and_period_rejected(db_session):
    block_code = f"TEST-BLOCK-{uuid4().hex[:8]}"
    first = CgwbGroundwaterObservation(
        block_code=block_code,
        category="safe",
        assessment_period="2024",
        source_url="https://indiawris.gov.in/wris/example",
    )
    db_session.add(first)
    await db_session.commit()

    duplicate = CgwbGroundwaterObservation(
        block_code=block_code,
        assessment_period="2024",  # same (block_code, assessment_period) pair
        category="critical",  # a different category doesn't excuse the duplicate
        source_url="https://indiawris.gov.in/wris/example-resubmit",
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError, match="uq_cgwb_block_period"):
        await db_session.commit()
    await db_session.rollback()


async def test_same_block_code_different_period_allowed(db_session):
    """The uniqueness constraint is on the (block_code, assessment_period)
    pair, not block_code alone — a new CGWB assessment cycle for the same
    block must be insertable, not rejected as a false duplicate."""
    block_code = f"TEST-BLOCK-{uuid4().hex[:8]}"
    db_session.add_all(
        [
            CgwbGroundwaterObservation(
                block_code=block_code,
                category="safe",
                assessment_period="2023",
                source_url="https://indiawris.gov.in/wris/example",
            ),
            CgwbGroundwaterObservation(
                block_code=block_code,
                category="semi_critical",
                assessment_period="2024",
                source_url="https://indiawris.gov.in/wris/example",
            ),
        ]
    )
    await db_session.commit()
