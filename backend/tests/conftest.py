import os

# Settings are read at import time by app.database.base (engine creation is
# lazy, but get_settings() itself is not) — these must be set before any
# `app.*` module is imported anywhere in the test session. A real DATABASE_URL
# is never required for the M0 test suite: DDL-compile tests work offline,
# and the auth test substitutes its own SQLite engine via dependency override.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-production")

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.user import AppUser


@pytest.fixture
async def sqlite_session_factory():
    """An isolated in-memory SQLite engine with just the app_user table.

    Used for the login flow test: app_user has no geometry/PostGIS-specific
    columns, so it is the one table that can be exercised end-to-end without
    a real Postgres instance. Every other table depends on PostGIS types and
    is validated instead via offline DDL compilation (test_schema_ddl.py) —
    see the M0 summary for why a live Postgres wasn't available to this
    environment.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(AppUser.__table__.create)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield session_factory

    await engine.dispose()
