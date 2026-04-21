"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import get_settings
from .logging import configure_logging, get_logger
from .routes import auth, chat, health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.app_env)
    log = get_logger("api")
    log.info("api.starting", env=settings.app_env, port=settings.port)
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
    return app


app = create_app()
