"""FastAPI application entrypoint."""

from __future__ import annotations

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
    admin_metrics,
    admin_overview,
    admin_prompts,
    admin_rag,
    admin_users,
    auth,
    chat,
    client_config,
    conversations,
    databases,
    feedback,
    health,
    sql,
)


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
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(users_bootstrap.run)

    from .audit.queue import get_queue as _get_audit_queue
    await _get_audit_queue().start()

    try:
        yield
    finally:
        try:
            await _get_audit_queue().stop()
        except Exception:  # noqa: BLE001
            pass
        log.info("api.stopping")


def create_app() -> FastAPI:
    """Construct the FastAPI app. Kept thin on purpose — all work in routers/services."""
    settings = get_settings()
    app = FastAPI(
        title="insightxpert.ai API",
        version="0.1.0",
        lifespan=lifespan,
    )
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
    app.include_router(sql.router)
    app.include_router(conversations.router)
    app.include_router(feedback.router)
    app.include_router(client_config.router)
    app.include_router(admin_users.router)
    app.include_router(admin_overview.router)
    app.include_router(admin_audit.router)
    app.include_router(admin_metrics.router)
    app.include_router(admin_conversations.router)
    app.include_router(admin_prompts.router)
    app.include_router(admin_rag.router)
    return app


app = create_app()
