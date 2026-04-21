"""/api/v1/admin/rag — admin ops over the RAG vector store.

Currently one endpoint: clear the auto-saved QA pairs (keeps DDL/docs/findings
intact — see ``rag.admin_service`` for rationale).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from ..auth.current_user import CurrentUser, require_admin
from ..rag import admin_service

router = APIRouter(prefix="/api/v1/admin/rag", tags=["admin-rag"])


@router.delete("/qa-pairs")
async def clear_qa_pairs(
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    count = await asyncio.to_thread(admin_service.clear_qa_pairs)
    return {"deleted": True, "count": count}
