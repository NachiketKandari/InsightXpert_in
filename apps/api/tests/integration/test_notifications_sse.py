"""Notification SSE stream + dispatch tests."""

from __future__ import annotations

import asyncio
import json

from insightxpert_api.automations import notifications as notif_module


async def test_dispatch_writes_and_pushes(user_client_automations):
    """create + dispatch — backlog hydration yields the created notification."""
    client, user = user_client_automations

    # Create a notification in DB, without dispatching.
    notif = notif_module.create(
        user.id,
        title="t",
        message="m",
        severity="warning",
    )

    # Drive one iteration of the stream; the backlog yields the pending notification.
    agen = notif_module.stream_for_user(client.app, user.id)
    first = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    parsed = json.loads(first)
    assert parsed["type"] == "notification_created"
    assert parsed["data"]["id"] == notif["id"]
    assert parsed["data"]["title"] == "t"

    # cleanup: close the emitter so the generator terminates.
    em = client.app.state.user_notification_emitters.get(user.id)
    if em is not None:
        await em.close()


async def test_dispatch_pushes_live_event(user_client_automations):
    """Subscribe, then dispatch a freshly-created notification — arrives on stream."""
    client, user = user_client_automations

    agen = notif_module.stream_for_user(client.app, user.id)

    # Prime the emitter with a live dispatch after the backlog (empty here).
    async def drive():
        notif = notif_module.create(
            user.id, title="live", message="hello", severity="info"
        )
        await notif_module.dispatch(client.app, user.id, notif)

    task = asyncio.create_task(drive())
    try:
        event = await asyncio.wait_for(agen.__anext__(), timeout=3.0)
    finally:
        await task
    parsed = json.loads(event)
    assert parsed["type"] == "notification_created"
    assert parsed["data"]["title"] == "live"

    em = client.app.state.user_notification_emitters.get(user.id)
    if em is not None:
        await em.close()


async def test_list_and_mark_read(user_client_automations):
    client, user = user_client_automations
    notif_module.create(user.id, title="t1", message="m", severity="info")
    notif_module.create(user.id, title="t2", message="m", severity="info")

    r = client.get("/api/v1/notifications")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2

    r = client.get("/api/v1/notifications/count")
    assert r.json()["count"] == 2

    r = client.post(f"/api/v1/notifications/{rows[0]['id']}/read")
    assert r.status_code == 200

    r = client.get("/api/v1/notifications?unread=true")
    assert len(r.json()) == 1

    r = client.post("/api/v1/notifications/mark-all-read")
    assert r.status_code == 200
    r = client.get("/api/v1/notifications/count")
    assert r.json()["count"] == 0
