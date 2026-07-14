from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import JobStatus, JobType


class ProgressStage(BaseModel):
    """One row of the honest execution timeline (M2B P8). Mirrors
    app/services/reporting/progress.py's stage shape exactly — that
    module is the only writer of this data."""

    id: str
    title: str
    status: Literal["pending", "running", "done", "failed"]
    started_at: datetime | None
    completed_at: datetime | None
    metadata: dict | None = None


class JobProgress(BaseModel):
    stages: list[ProgressStage]


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: JobType
    status: JobStatus
    entity_id: UUID | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    # None for jobs created before this column existed, and for any job
    # type other than farm_report — the API and frontend both treat a
    # missing timeline as "nothing to show," never as an error.
    progress: JobProgress | None = None
