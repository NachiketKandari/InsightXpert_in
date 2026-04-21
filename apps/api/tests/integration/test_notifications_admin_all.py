"""GET /api/v1/notifications/all — admin cross-user feed."""

from __future__ import annotations

from insightxpert_api.automations import notifications as notif_module


def test_admin_sees_all_users_notifications(
    admin_client_automations, user_client_automations
):
    """Admin's /all endpoint returns notifications for every user, enriched
    with user_email; non-admins get 403."""
    user_client, user = user_client_automations
    admin_client, admin = admin_client_automations

    notif_module.create(user.id, title="user-notif", message="u", severity="info")
    notif_module.create(admin.id, title="admin-notif", message="a", severity="warning")

    # Admin sees both.
    r = admin_client.get("/api/v1/notifications/all")
    assert r.status_code == 200
    rows = r.json()
    titles = {row["title"] for row in rows}
    assert {"user-notif", "admin-notif"} <= titles
    # Enrichment: user_email present on each row.
    for row in rows:
        assert "user_email" in row

    # Regular user is forbidden.
    r2 = user_client.get("/api/v1/notifications/all")
    assert r2.status_code == 403


def test_admin_all_unread_filter(admin_client_automations):
    admin_client, admin = admin_client_automations
    n1 = notif_module.create(admin.id, title="n1", message="x", severity="info")
    notif_module.create(admin.id, title="n2", message="y", severity="info")

    # Mark one read.
    admin_client.post(f"/api/v1/notifications/{n1['id']}/read")

    unread = admin_client.get("/api/v1/notifications/all?unread=true").json()
    titles = {r["title"] for r in unread}
    assert "n2" in titles
    assert "n1" not in titles


def test_admin_all_feature_flag_off(admin_client):
    """With AUTOMATIONS_ENABLED=false, the route isn't mounted → 404."""
    client, _ = admin_client
    r = client.get("/api/v1/notifications/all")
    assert r.status_code == 404
