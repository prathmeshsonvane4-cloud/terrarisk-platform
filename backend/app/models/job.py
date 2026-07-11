import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import JobStatus, JobType
from app.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class Job(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Durable async job tracking, shared by both services (Blueprint §03/§09
    CTO review finding: job state must survive a process restart, so it
    lives in the database, not in-process memory).
    """

    __tablename__ = "job"

    type: Mapped[JobType] = mapped_column(pg_enum(JobType, "job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(pg_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.PENDING)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
