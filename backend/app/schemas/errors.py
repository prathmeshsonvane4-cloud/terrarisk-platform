from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Single error envelope used by every endpoint (Blueprint §03) — a
    client only ever needs to know one shape for a failure response,
    regardless of which endpoint returned it."""

    error: ErrorDetail
