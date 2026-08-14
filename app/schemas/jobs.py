from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.schemas.responses import Usage


class JobStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"
    EXPIRED = "expired"


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    openai_response_id: str | None = None
    created_at: datetime
    expires_at: datetime
    status_url: str
    correlation_id: str
    model: str | None = None
    output_text: str | None = None
    usage: Usage | None = None


class BackgroundJobResponse(BaseModel):
    id: str
    status: JobStatus
    created_at: datetime
    expires_at: datetime
    status_url: str
    correlation_id: str
    model: str | None = None
    output_text: str | None = None
    usage: Usage | None = None
