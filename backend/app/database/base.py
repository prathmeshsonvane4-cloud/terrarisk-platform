from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base — every model in app.models inherits from this
    so Alembic and app.models.__init__ can discover the full schema from one
    place."""


def _build_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=settings.debug, future=True)


# Engine creation is lazy (SQLAlchemy does not connect until first use), so
# importing this module never requires a reachable database — this keeps
# `import app.main` safe in contexts (like tests) that provide their own
# engine via dependency override.
engine = _build_engine()

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
