import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    # Generic sa.Uuid, not the Postgres-specific dialect type: compiles to a
    # native UUID column on Postgres (identical DDL) while still letting
    # models be exercised against SQLite in tests that don't need PostGIS
    # geometry columns (see backend/tests/test_auth.py).
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
