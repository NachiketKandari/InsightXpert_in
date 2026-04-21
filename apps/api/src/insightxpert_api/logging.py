"""Structured JSON logging (Cloud Logging compatible in prod, pretty in dev)."""

from __future__ import annotations

import logging

import structlog


def configure_logging(env: str) -> None:
    """Configure structlog for the given environment.

    - ``local``: pretty console renderer (devx).
    - anything else: JSON renderer (Cloud Logging ingests cleanly).
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if env == "local":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger tagged with ``name``."""
    return structlog.get_logger(name)
