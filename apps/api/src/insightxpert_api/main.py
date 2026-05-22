"""FastAPI application entrypoint."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import get_settings
from .logging import configure_logging, get_logger
from .routes import (
    admin_audit,
    admin_conversations,
    admin_databases,
    admin_metrics,
    admin_overview,
    admin_performance,
    admin_prompts,
    admin_rag,
    admin_users,
    auth,
    automations as automations_routes,
    chat,
    client_config,
    config as config_routes,
    connections,
    conversations,
    databases,
    feedback,
    health,
    insights as insights_routes,
    internal as internal_routes,
    notifications as notifications_routes,
    shared_snapshots as shared_snapshots_routes,
    public_shares as public_shares_routes,
    sql,
    voice as voice_routes,
)

# ---------------------------------------------------------------------------
# SSE idle-reaper constants
# ---------------------------------------------------------------------------

_REAPER_INTERVAL_S = 60          # How often the reaper wakes up.
_EMITTER_IDLE_TTL_S = 900        # 15 minutes of no activity → eligible for eviction.


async def _sse_idle_reaper(app: FastAPI) -> None:
    """Background task: evict SSE emitters that are idle and have no subscriber.

    Runs every ``_REAPER_INTERVAL_S`` seconds. Uses the ``_emitters_lock`` on
    ``app.state`` to safely mutate ``user_notification_emitters``.
    """
    import asyncio
    import time

    from .logging import get_logger as _get_log
    from .observability import increment_sse_evicted

    log = _get_log("sse.reaper")

    while True:
        await asyncio.sleep(_REAPER_INTERVAL_S)
        try:
            lock = getattr(app.state, "_emitters_lock", None)
            if lock is None:
                continue
            emitters: dict = getattr(app.state, "user_notification_emitters", {})
            now = time.monotonic()
            to_evict = [
                uid
                for uid, em in list(emitters.items())
                if (now - em.last_activity_at) > _EMITTER_IDLE_TTL_S
                and not em.has_subscriber
            ]
            if not to_evict:
                continue
            async with lock:
                evicted = 0
                for uid in to_evict:
                    em = emitters.pop(uid, None)
                    if em is not None:
                        # Close cleanly so any pending consumer drains the sentinel.
                        try:
                            await em.close()
                        except Exception:  # noqa: BLE001
                            pass
                        evicted += 1
            if evicted:
                increment_sse_evicted(evicted)
                log.info(
                    "sse.reaper.evicted",
                    evicted=evicted,
                    remaining=len(emitters),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("sse.reaper.error", error=str(exc), error_type=type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.app_env)
    log = get_logger("api")
    log.info("api.starting", env=settings.app_env, port=settings.port)

    import asyncio
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from .users import bootstrap as users_bootstrap

    api_dir = Path(__file__).resolve().parents[2]  # apps/api
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    # Escape `%` for configparser so URL-encoded passwords (e.g. `%40` for `@`) survive.
    cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(users_bootstrap.run)

    from .audit.queue import get_queue as _get_audit_queue
    await _get_audit_queue().start()

    # --- automations (C1) --------------------------------------------------
    app.state.user_notification_emitters = {}
    # Lock protecting mutation of user_notification_emitters dict.
    app.state._emitters_lock = asyncio.Lock()

    app.state.automation_scheduler = None
    if settings.automations_enabled:
        from .automations.scheduler import build_scheduler

        scheduler = build_scheduler(
            app,
            mode=settings.automations_scheduler_mode,
            tick_seconds=settings.automations_scheduler_tick_seconds,
        )
        await scheduler.start()
        app.state.automation_scheduler = scheduler
        log.info(
            "automations.enabled",
            mode=settings.automations_scheduler_mode,
        )

    # --- SSE idle reaper ---------------------------------------------------
    reaper_task = asyncio.create_task(
        _sse_idle_reaper(app), name="sse-idle-reaper"
    )

    try:
        yield
    finally:
        # Cancel the reaper first so it doesn't race with teardown.
        reaper_task.cancel()
        try:
            await reaper_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

        try:
            await _get_audit_queue().stop()
        except Exception:  # noqa: BLE001
            pass
        sched = getattr(app.state, "automation_scheduler", None)
        if sched is not None:
            try:
                await sched.stop()
            except Exception:  # noqa: BLE001
                pass
        from .db.engine import _request_engine, _background_engine

        if _request_engine is not None:
            try:
                _request_engine.dispose()
            except Exception:  # noqa: BLE001
                pass
        if _background_engine is not None:
            try:
                _background_engine.dispose()
            except Exception:  # noqa: BLE001
                pass

        log.info("api.stopping")


def create_app() -> FastAPI:
    """Construct the FastAPI app. Kept thin on purpose — all work in routers/services."""
    settings = get_settings()

    # Sentry must init before FastAPI() so its FastApiIntegration can patch
    # the ASGI app on construction. No-op when SENTRY_DSN is empty.
    from .sentry import init_sentry
    init_sentry(settings)

    app = FastAPI(
        title="insightxpert.ai API",
        version="0.1.0",
        lifespan=lifespan,
    )
    # Timing middleware MUST be first so it wraps the entire stack
    # and captures true end-to-end wall-clock latency.
    from .middleware.timing import TimingMiddleware
    app.add_middleware(TimingMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    from .audit.middleware import register as _register_audit
    _register_audit(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(databases.router)
    app.include_router(connections.router)
    app.include_router(sql.router)
    app.include_router(conversations.router)
    app.include_router(feedback.router)
    app.include_router(insights_routes.router)
    app.include_router(client_config.router)
    app.include_router(config_routes.router)
    app.include_router(admin_users.router)
    app.include_router(admin_overview.router)
    app.include_router(admin_performance.router)
    app.include_router(admin_audit.router)
    app.include_router(admin_metrics.router)
    app.include_router(admin_conversations.router)
    app.include_router(admin_prompts.router)
    app.include_router(admin_rag.router)
    app.include_router(admin_databases.router)
    app.include_router(shared_snapshots_routes.router)
    app.include_router(public_shares_routes.router)
    app.include_router(voice_routes.router)

    from .routes import sentry_debug as sentry_debug_route
    app.include_router(sentry_debug_route.router)

    # Internal scheduler endpoint is always mounted — it returns 503 when
    # automations are disabled, which external callers can detect.
    app.include_router(internal_routes.router)

    # Store process start time for the admin/performance endpoint.
    app.state.process_started_at = time.monotonic()

    # User-facing automations + notifications routes only exist when enabled.
    # templates_router must be included BEFORE router so that
    # /api/v1/automations/templates resolves to the templates handler, not the
    # parametric /{automation_id} route.
    if settings.automations_enabled:
        app.include_router(automations_routes.templates_router)
        app.include_router(automations_routes.router)
        app.include_router(notifications_routes.router)

    # Prometheus-formatted metrics endpoint (no auth — TODO-SECURITY: firewall
    # this path or require an internal-only header in prod before public exposure).
    from .routes import metrics as metrics_route
    app.include_router(metrics_route.router)

    return app


app = create_app()
