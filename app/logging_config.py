"""Centralised logging configuration for the Nutribox backend.

Usage — import and call once at application startup, before any other imports
that use logging:

    from app.logging_config import setup_logging
    setup_logging()

Reads the following environment variables:
    LOG_LEVEL  – Python log level name (default: INFO)
    LOG_FORMAT – "json" for structured JSON output (production), anything else
                 for human-readable coloured output (default: text)
"""

import logging
import os
import sys
from datetime import datetime, timezone


# ── JSON formatter (production) ──────────────────────────────────────────────

class _JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line — easy to ingest in CloudWatch,
    DataDog, Loki, or any structured-log pipeline."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info
        return json.dumps(payload, default=str)


# ── Human-readable formatter (development) ───────────────────────────────────

_TEXT_FMT = "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s"
_TEXT_DATEFMT = "%Y-%m-%d %H:%M:%S"


# ── Public API ───────────────────────────────────────────────────────────────

def setup_logging() -> None:
    """Configure the root logger based on environment variables."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.getenv("LOG_FORMAT", "text").lower()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FMT, datefmt=_TEXT_DATEFMT))

    # Reset any existing handlers on the root logger
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet down noisy third-party loggers in production
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
