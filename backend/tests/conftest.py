import os

from dotenv import load_dotenv

# Settings are read at import time by app.database.base (engine creation is
# lazy, but get_settings() itself is not) — these must be resolved before any
# `app.*` module is imported anywhere in the test session.
#
# Load the real backend/.env first (if present) so local integration tests
# (e.g. test_report_generator.py) connect to the real local PostGIS instance
# rather than a placeholder. load_dotenv() never overrides a variable already
# present in the environment, so this is safe to call unconditionally. Only
# after that do the setdefault() calls below fill in safe placeholders for
# whatever remains unset — e.g. a fresh CI checkout with no .env and no
# secrets, where only the fully-offline tests (DDL compile, pure unit tests)
# are expected to run; anything needing a real DATABASE_URL skips itself
# cleanly (see the db_session fixture in test_report_generator.py).
load_dotenv()
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
