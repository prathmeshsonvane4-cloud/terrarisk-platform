from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import JobStatus, JobType


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: JobType
    status: JobStatus
    entity_id: UUID | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
