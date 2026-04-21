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

    try:
        yield
    finally:
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
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(databases.router)
    app.include_router(sql.router)
    app.include_router(conversations.router)
    app.include_router(feedback.router)
    app.include_router(client_config.router)
    return app


app = create_app()
