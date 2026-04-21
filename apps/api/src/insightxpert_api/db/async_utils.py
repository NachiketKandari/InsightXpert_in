"""Wrap blocking DB calls so the event loop stays responsive.

Every route/service path MUST route SQLAlchemy calls through run_in_thread
(or asyncio.to_thread directly). A missed call stalls the loop for all
concurrent requests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


async def run_in_thread(fn: Callable[..., T], *args, **kwargs) -> T:
    return await asyncio.to_thread(fn, *args, **kwargs)
