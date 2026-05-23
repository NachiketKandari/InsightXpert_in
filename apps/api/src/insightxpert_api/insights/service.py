"""Insights service — thin async wrapper around the repository.

Business logic lives here; the repository is pure SQL. Every method delegates
to the repository via ``asyncio.to_thread`` so the event loop stays free.
"""

from __future__ import annotations

import asyncio

from . import repository as repo


class InsightService:
    """Thin service that wraps repository calls with asyncio.to_thread."""

    async def create(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str | None = None,
        content: str = "",
        summary: str | None = None,
        title: str | None = None,
        user_note: str | None = None,
        source: str = "manual",
    ) -> dict:
        return await asyncio.to_thread(
            repo.insert_insight,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            content=content,
            summary=summary,
            title=title,
            user_note=user_note,
            source=source,
        )

    async def list_for_user(
        self,
        user_id: str,
        *,
        bookmarked: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        return await asyncio.to_thread(
            repo.list_insights,
            user_id,
            bookmarked=bookmarked,
            limit=limit,
        )

    async def list_all(
        self,
        *,
        limit: int = 200,
    ) -> list[dict]:
        return await asyncio.to_thread(
            repo.list_all_insights,
            limit=limit,
        )

    async def count(self, user_id: str) -> int:
        return await asyncio.to_thread(repo.count_insights, user_id)

    async def bookmark(self, insight_id: str, user_id: str, bookmarked: bool) -> bool:
        return await asyncio.to_thread(
            repo.update_bookmark, insight_id, user_id, bookmarked
        )

    async def delete(self, insight_id: str, user_id: str) -> bool:
        return await asyncio.to_thread(repo.delete_insight, insight_id, user_id)
