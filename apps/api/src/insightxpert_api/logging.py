"""Structured logging — console in dev, JSON + Cloud Logging in prod.

Routes structlog through Python stdlib logging. Handlers:

* stdout: INFO+  (console renderer in local; JSON → Cloud Logging in prod)
* file:   DEBUG+ (local only — rotated JSON, 10 MB × 5 backups)

In production (Cloud Run) the file handler is skipped since stdout is
automatically piped to Cloud Logging and the container filesystem is
ephemeral.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog


def configure_logging(env: str) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    # --- stdlib logging setup (handlers) ------------------------------------
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Clear any handlers from previous calls (e.g. test cache clearing).
    root.handlers.clear()

    # Stdout — INFO+ (same as before, just routed through stdlib now).
    stdout = logging.StreamHandler()
    stdout.setLevel(logging.INFO)
    if env == "local":
        stdout.setFormatter(_ConsoleFormatter())
    else:
        stdout.setFormatter(logging.Formatter(
            "%(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
        ))
    root.addHandler(stdout)

    # File — DEBUG+ (local only; stdout goes to Cloud Logging in prod).
    if env == "local":
        log_dir = Path(__file__).resolve().parents[3] / "logs"
        log_dir.mkdir(exist_ok=True)
        # DECISION(D-075): File-based log rotation in dev only (10 MB x 5
        # backups, JSON format). Production logs go to stdout via JSONRenderer
        # (Cloud Run captures stdout → Cloud Logging). No file I/O in prod.
        file_handler = RotatingFileHandler(
            log_dir / "api.log",
            maxBytes=10_485_760,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(_JSONFileFormatter())
        root.addHandler(file_handler)

    # Suppress verbose SQLAlchemy engine logs (every SQL statement with
    # params) at DEBUG level — they flood the file log and add disk I/O.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # DECISION(D-070): structlog with ConsoleRenderer (local dev, human-readable)
    # and JSONRenderer (prod, machine-parseable by Cloud Logging).
    # contextvars for request-scoped fields; stdlib logging bridge.
    # --- structlog (processors + renderer) ----------------------------------
    if env == "local":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger tagged with ``name``."""
    return structlog.get_logger(name)


class _ConsoleFormatter(logging.Formatter):
    """Pass-through for structlog's ConsoleRenderer — structlog already formats."""

    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


class _JSONFileFormatter(logging.Formatter):
    """Minimal JSON envelope so file logs are machine-readable.

    Does NOT re-serialize structlog's already-JSON output in prod mode.
    In local mode, structlog emits pretty text; this wraps it in a JSON
    envelope with timestamp, level, and logger name so the file stays
    parseable.
    """

    def format(self, record: logging.LogRecord) -> str:
        import json
        return json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }, ensure_ascii=False)
