"""Shared LLM concurrency semaphore — one cap across all providers."""

from __future__ import annotations

import asyncio
import os

_SEM: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        cap = int(os.environ.get("LLM_MAX_CONCURRENCY", "3") or 3)
        _SEM = asyncio.Semaphore(max(1, cap))
    return _SEM


def reset_llm_semaphore(n: int) -> None:
    global _SEM
    _SEM = asyncio.Semaphore(max(1, int(n)))
