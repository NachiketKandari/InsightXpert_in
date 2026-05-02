"""Unit tests for the scheduler modes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from insightxpert_api.automations.scheduler import (
    EmbeddedScheduler,
    ExternalScheduler,
    build_scheduler,
)


class _FakeApp:
    def __init__(self):
        class _S:
            pass

        self.state = _S()


@pytest.mark.asyncio
async def test_embedded_scheduler_starts_apscheduler():
    app = _FakeApp()
    with patch(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler"
    ) as MockSched:
        inst = MagicMock()
        MockSched.return_value = inst
        sched = EmbeddedScheduler(app, tick_seconds=5)
        await sched.start()
        assert inst.add_job.called
        assert inst.start.called
        await sched.stop()
        assert inst.shutdown.called


@pytest.mark.asyncio
async def test_external_scheduler_noop():
    app = _FakeApp()
    sched = ExternalScheduler(app)
    await sched.start()
    await sched.stop()
    sched.refresh_jobs()  # just doesn't raise


@pytest.mark.asyncio
async def test_scheduler_job_coalesces_missed_ticks():
    from fastapi import FastAPI

    app = FastAPI()
    sched = EmbeddedScheduler(app, tick_seconds=30)
    await sched.start()
    try:
        job = sched._scheduler.get_job("automations_tick")
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        await sched.stop()


def test_build_scheduler_selects_mode():
    app = _FakeApp()
    assert isinstance(build_scheduler(app, mode="external", tick_seconds=30), ExternalScheduler)
    assert isinstance(build_scheduler(app, mode="embedded", tick_seconds=30), EmbeddedScheduler)
