from fastapi.testclient import TestClient


def test_unlock_rejects_wrong_password(client: TestClient):
    r = client.post("/api/v1/auth/unlock", json={"password": "nope"})
    assert r.status_code == 401


def test_unlock_sets_cookie_on_success(client: TestClient):
    r = client.post("/api/v1/auth/unlock", json={"password": "test-pw"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert "ix_session" in r.cookies


def test_me_requires_session(client: TestClient):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_returns_session_id_when_authed(authed_client: TestClient):
    r = authed_client.get("/api/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert len(body["session_id"]) >= 16


def test_me_rejects_bad_token(client: TestClient):
    client.cookies.set("ix_session", "garbage")
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 403


def test_logout_clears_cookie(authed_client: TestClient):
    r = authed_client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    # After logout, /me should 401 again
    authed_client.cookies.clear()
    r2 = authed_client.get("/api/v1/auth/me")
    assert r2.status_code == 401


def test_bearer_token_fallback_works(client: TestClient):
    # Unlock to get a token, then use it via Authorization header
    r = client.post("/api/v1/auth/unlock", json={"password": "test-pw"})
    token = r.cookies.get("ix_session")
    client.cookies.clear()
    r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
