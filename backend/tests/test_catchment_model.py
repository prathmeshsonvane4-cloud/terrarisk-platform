"""Integration tests for the Catchment model's database-level CHECK
constraints, against a real local PostGIS instance — CheckConstraint
enforcement cannot be exercised via offline DDL compilation (that only
proves the constraint *compiles*, not that Postgres *enforces* it), and
GeoAlchemy2 geometry columns have no meaningful SQLite backend in this
project. Mirrors tests/services/test_report_generator.py's exact
skip-cleanly-without-Docker pattern.

This is the specific test the TDR (§4) found missing in Blueprint v1 and
required for v2: proof that an oversized or overly complex catchment can
never be persisted, not just a comment saying it can't (Blueprint v2 D9).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Point, Polygon
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal, engine
from app.models.catchment import Catchment
from app.models.enums import UserRole
from app.models.user import AppUser

_SMALL_VALID_POLYGON = Polygon([(76.0, 18.0), (76.01, 18.0), (76.01, 18.01), (76.0, 18.01), (76.0, 18.0)])


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


@pytest_asyncio.fixture
async def user(db_session):
    """A single AppUser to satisfy Catchment.created_by's NOT NULL FK."""
    app_user = AppUser(
        email=f"test-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("test-password"),
        full_name="Test Programme Officer",
        role=UserRole.PROGRAMME_OFFICER,
        is_active=True,
    )
    db_session.add(app_user)
    await db_session.flush()
    return app_user


async def test_valid_catchment_persists(db_session, user):
    """Sanity check the constraints aren't accidentally rejecting legitimate
    data — a mid-range area, a simple few-vertex polygon."""
    catchment = Catchment(
        name="Valid Test Catchment",
        geometry=from_shape(MultiPolygon([_SMALL_VALID_POLYGON]), srid=4326),
        area_ha=100.0,
        created_by=user.id,
    )
    db_session.add(catchment)
    await db_session.commit()
    await db_session.refresh(catchment)
    assert catchment.id is not None


async def test_undersized_area_rejected_by_check_constraint(db_session, user):
    catchment = Catchment(
        name="Too Small",
        geometry=from_shape(MultiPolygon([_SMALL_VALID_POLYGON]), srid=4326),
        area_ha=0.1,  # below the 0.5 ha floor
        created_by=user.id,
    )
    db_session.add(catchment)
    with pytest.raises(IntegrityError, match="chk_catchment_area"):
        await db_session.commit()
    await db_session.rollback()


async def test_oversized_area_rejected_by_check_constraint(db_session, user):
    catchment = Catchment(
        name="Too Big",
        geometry=from_shape(MultiPolygon([_SMALL_VALID_POLYGON]), srid=4326),
        area_ha=60000.0,  # above the 50,000 ha (500 km^2) ceiling
        created_by=user.id,
    )
    db_session.add(catchment)
    with pytest.raises(IntegrityError, match="chk_catchment_area"):
        await db_session.commit()
    await db_session.rollback()


async def test_excessive_vertex_count_rejected_by_check_constraint(db_session, user):
    """A high-resolution circular buffer comfortably exceeds 2000 vertices
    (resolution=700 => roughly 4*700 boundary points) while staying inside
    the valid area range — isolates the vertex-count constraint from the
    area constraint rather than tripping both at once."""
    complex_polygon = Point(76.0, 18.0).buffer(0.05, resolution=700)
    catchment = Catchment(
        name="Too Complex",
        geometry=from_shape(MultiPolygon([complex_polygon]), srid=4326),
        area_ha=100.0,  # deliberately a plausible value, independent of the
        # buffer's real area — this test isolates the vertex constraint only
        created_by=user.id,
    )
    db_session.add(catchment)
    with pytest.raises(IntegrityError, match="chk_catchment_vertex_count"):
        await db_session.commit()
    await db_session.rollback()
