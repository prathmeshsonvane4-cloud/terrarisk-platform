"""Structured (JSON) logging configuration.

Every log record is emitted as one JSON object per line — standard
practice for downstream log aggregation (CloudWatch, Stackdriver, etc.) in
a production deployment. Only operational fields are ever included: a
timestamp, level, logger name, message, exception traceback (server-side
only — never returned through the API, see app/main.py's exception
handlers), and whatever safe `extra` fields a call site provides (e.g.
job_id, farm_id, request path). No log call anywhere in this codebase
passes passwords, JWTs, service-account keys, or other secrets as `extra`
fields — enforced by convention and code review, since Python's logging
module has no way to redact arbitrary structured fields automatically.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_RESERVED_LOG_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "asctime",
}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # SQLAlchemy's engine logger is extremely verbose at INFO (every SQL
    # statement) — appropriate for local debugging (app/database/base.py
    # already gates it behind settings.debug), noisy for structured
    # production logs otherwise.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
