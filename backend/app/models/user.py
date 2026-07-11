import uuid

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import UserRole
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class AppUser(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Bank-side login. Minimal for M0 — just enough for role-scoped auth;
    onboarding/permissions UI is not in scope until a later milestone."""

    __tablename__ = "app_user"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
