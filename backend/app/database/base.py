from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base — every model in app.models inherits from this
    so Alembic and app.models.__init__ can discover the full schema from one
    place."""


def _build_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        # RC2 reliability finding: postgres runs as its own independently
        # restartable container (docker-compose.prod.yml) — without
        # pre-ping, a connection already checked into the pool when
        # postgres restarts goes stale, and the *next* request to check it
        # out fails with a raw connection error instead of transparently
        # getting a fresh connection. pool_pre_ping issues a cheap `SELECT
        # 1` on checkout and discards a dead connection instead of handing
        # it to the caller. pool_recycle is defense against the same class
        # of silent drop (an idle connection reaped by a stateful
        # proxy/firewall) without requiring a restart to trigger it.
        pool_pre_ping=True,
        pool_recycle=1800,
    )


# Engine creation is lazy (SQLAlchemy does not connect until first use), so
# importing this module never requires a reachable database — this keeps
# `import app.main` safe in contexts (like tests) that provide their own
# engine via dependency override.
engine = _build_engine()

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
