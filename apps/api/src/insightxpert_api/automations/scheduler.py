"""Scheduler abstraction for Phase C1.

Two modes (selected via ``settings.automations_scheduler_mode``):

    * ``embedded`` — APScheduler ``AsyncIOScheduler`` inside the FastAPI process.
      Good for dev + single-replica prod. Each job is a single ticker that
      calls :func:`runner.run_due_automations` on a fixed interval.

    * ``external`` — no-op. Scheduling is done by an external cron hitting
      ``POST /api/internal/run-due-automations``.

Both delegate execution to a single function in ``runner.py`` — the scheduler
never parses cron itself, it just triggers the dispatcher on a cadence.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from fastapi import FastAPI

from . import runner

logger = logging.getLogger("insightxpert_api.automations.scheduler")


class AutomationScheduler(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def refresh_jobs(self) -> None: ...


class EmbeddedScheduler:
    """APScheduler-backed scheduler. Ticks every ``tick_seconds`` to
    re-dispatch due automations via the runner.
    """

    def __init__(self, app: FastAPI, tick_seconds: int = 30) -> None:
        self._app = app
        self._tick = max(1, int(tick_seconds))
        self._scheduler = None  # type: ignore[assignment]
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        # Lazy import so tests can stub out apscheduler cleanly.
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._tick_callback,
            trigger=IntervalTrigger(seconds=self._tick),
            id="automations_tick",
            replace_existing=True,
            misfire_grace_time=self._tick,
        )
        self._scheduler.start()
        self._started = True
        logger.info(
            "embedded scheduler started (tick=%ss)", self._tick
        )

    async def _tick_callback(self) -> None:
        try:
            await runner.run_due_automations(self._app)
        except Exception as exc:  # noqa: BLE001
            logger.error("embedded scheduler tick failed: %s", exc, exc_info=True)

    async def stop(self) -> None:
        if self._scheduler is not None and self._started:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        self._started = False
        logger.info("embedded scheduler stopped")

    def refresh_jobs(self) -> None:
        """No-op — the ticker rediscovers due automations every tick."""
        return None


class ExternalScheduler:
    """No-op scheduler. Scheduling is delegated to an external cron."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def start(self) -> None:
        logger.info("external scheduler active (no in-process jobs)")

    async def stop(self) -> None:
        return None

    def refresh_jobs(self) -> None:
        return None


def build_scheduler(app: FastAPI, *, mode: str, tick_seconds: int) -> AutomationScheduler:
    if mode == "external":
        return ExternalScheduler(app)
    return EmbeddedScheduler(app, tick_seconds=tick_seconds)


__all__ = [
    "AutomationScheduler",
    "EmbeddedScheduler",
    "ExternalScheduler",
    "build_scheduler",
]
