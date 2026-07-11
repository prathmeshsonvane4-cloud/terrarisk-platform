import enum
import uuid
from datetime import datetime
from typing import TypeVar

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

_E = TypeVar("_E", bound=enum.Enum)


def pg_enum(enum_cls: type[_E], name: str) -> SAEnum:
    """A Postgres-backed Enum column bound by the enum's *value*, not its
    member name.

    SQLAlchemy's Enum type binds/reads using the Python member name
    ("VILLAGE") by default — but every native Postgres enum type in this
    schema was created (Alembic migration 0001) with the lowercase
    *values* ("village") as its only valid labels, matching the enum
    class's own str value. Without values_callable, an insert like
    `BoundaryLevel.VILLAGE` fails against real Postgres with
    "invalid input value for enum boundary_level: VILLAGE" — caught during
    M1 integration testing against a live database, masked in M0 because
    the only enum-bearing table exercised so far ran against SQLite, where
    the mismatch was accidentally self-consistent on both write and read.
    """
    return SAEnum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])


class UUIDPrimaryKeyMixin:
    # Generic sa.Uuid, not the Postgres-specific dialect type: compiles to a
    # native UUID column on Postgres (identical DDL) while still letting
    # models be exercised against SQLite in tests that don't need PostGIS
    # geometry columns (see backend/tests/test_auth.py).
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
