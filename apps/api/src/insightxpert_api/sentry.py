"""Sentry initialization — error tracking + incident detection.

Called once from ``main.create_app`` BEFORE the ``FastAPI`` instance is
constructed, because ``sentry_sdk.integrations.fastapi`` patches FastAPI at
import-sites that run during app construction.

When ``SENTRY_DSN`` is empty this becomes a no-op — safe for tests and
fresh clones without incident tooling configured.
"""

from __future__ import annotations

import logging

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from .config import Settings

_initialized = False


def init_sentry(settings: Settings) -> bool:
    """Initialize Sentry from settings. Returns True iff Sentry was turned on.

    Idempotent — subsequent calls after the first successful init are no-ops.
    """
    global _initialized
    if _initialized:
        return True
    if not settings.sentry_dsn:
        return False
    # Don't phone home from the test suite — error-path tests would pollute
    # the real incident project. `pytest` imports this module indirectly via
    # main.py's top-level ``app = create_app()``, so we can't rely on
    # fixtures alone to gate DSN.
    import sys
    if "pytest" in sys.modules:
        return False

    environment = settings.sentry_environment or settings.app_env
    release = settings.sentry_release or None

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=environment,
        release=release,
        send_default_pii=settings.sentry_send_default_pii,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
            AsyncioIntegration(),
            LoggingIntegration(
                level=logging.INFO,        # breadcrumbs from INFO+
                event_level=logging.ERROR, # events from ERROR+
            ),
        ],
    )
    _initialized = True
    return True
