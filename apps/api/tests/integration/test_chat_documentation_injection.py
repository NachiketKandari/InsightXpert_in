"""Integration test: chat dispatcher injects profile-derived docs into orchestrator.

Regression for the bug where the analyst's system prompt always carried the
hardcoded UPI / sender_state / fraud_flag block regardless of which database
the user had selected. The chat route must now load the active DB's profile,
render it via ``documentation_from_profile``, and pass the result into
``orchestrator_loop`` as ``documentation_override``.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from insightxpert_api.vendored.agents_core.api.models import ChatChunk as V
from insightxpert_api.vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnStats,
    DatabaseProfile,
    TableProfile,
)


def _schools_profile() -> DatabaseProfile:
    return DatabaseProfile(
        db_id="california_schools",
        tables=[
            TableProfile(
                name="schools",
                row_count=17_686,
                columns=[
                    ColumnProfile(
                        name="cdscode",
                        type="TEXT",
                        stats=ColumnStats(
                            count=17_686, null_count=0, distinct_count=17_686
                        ),
                    ),
                    ColumnProfile(
                        name="school",
                        type="TEXT",
                        stats=ColumnStats(
                            count=17_686, null_count=0, distinct_count=17_500
                        ),
                    ),
                    ColumnProfile(
                        name="district",
                        type="TEXT",
                        stats=ColumnStats(
                            count=17_686, null_count=0, distinct_count=1_000
                        ),
                    ),
                ],
            ),
        ],
    )


def test_chat_passes_profile_docs_to_orchestrator(authed_client: TestClient):
    """The dispatcher loads a profile, renders it, and forwards as override."""
    captured: dict = {}

    async def stub(**kwargs):
        captured.update(kwargs)
        cid = kwargs.get("conversation_id") or ""
        yield V(
            type="answer_generated",
            data={"text": "ok"},
            conversation_id=cid,
            timestamp=0.0,
        )

    with patch("insightxpert_api.routes.chat.orchestrator_loop", new=stub), patch(
        "insightxpert_api.routes.chat.ProfileService"
    ) as ProfSvc:
        ProfSvc.return_value.load.return_value = _schools_profile()
        r = authed_client.post(
            "/api/v1/chat/poll",
            json={
                "message": "how many schools?",
                "db_id": "california_schools",
                "agent_mode": "basic",
            },
        )
        assert r.status_code == 200, r.text

    docs = captured.get("documentation_override")
    assert docs, "documentation_override was not forwarded to orchestrator_loop"
    # Profile-derived markers — confirms the schools profile was rendered.
    assert "schools" in docs
    assert "california_schools" in docs
    # Hard guardrail: the old hardcoded UPI block must be fully gone.
    for forbidden in ("UPI", "fraud_flag", "sender_state", "Indian Rupees", "₹"):
        assert forbidden not in docs, (
            f"chat doc-injection still leaks '{forbidden}' — "
            "the hardcoded UPI block should be replaced by profile docs."
        )


def test_chat_falls_back_to_empty_when_profile_missing(authed_client: TestClient):
    """When no profile is available, the dispatcher passes None and the
    orchestrator's empty fallback kicks in. The chat route must NOT crash and
    must NOT inject the legacy UPI text from anywhere."""
    captured: dict = {}

    async def stub(**kwargs):
        captured.update(kwargs)
        cid = kwargs.get("conversation_id") or ""
        yield V(
            type="answer_generated",
            data={"text": "ok"},
            conversation_id=cid,
            timestamp=0.0,
        )

    with patch("insightxpert_api.routes.chat.orchestrator_loop", new=stub), patch(
        "insightxpert_api.routes.chat.ProfileService"
    ) as ProfSvc:
        ProfSvc.return_value.load.return_value = None
        r = authed_client.post(
            "/api/v1/chat/poll",
            json={
                "message": "anything",
                "db_id": "california_schools",
                "agent_mode": "basic",
            },
        )
        assert r.status_code == 200, r.text

    # When profile is absent we explicitly forward None — the orchestrator's
    # empty DOCUMENTATION fallback handles the rest.
    assert captured.get("documentation_override") is None
