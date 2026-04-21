from __future__ import annotations

import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from insightxpert_api.auth.current_user import CurrentUser, get_current_user
from insightxpert_api.auth.session import SessionSigner
from insightxpert_api.config import get_settings
from insightxpert_api.users import repository, service
from insightxpert_api.users.models import CreateUserInput


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    def who(cu: CurrentUser = Depends(get_current_user)):
        return {"id": cu.id, "role": cu.role}

    return app


def _set_session(client: TestClient, user_id: str, role: str) -> None:
    token = SessionSigner(get_settings()).issue(user_id=user_id, role=role)
    client.cookies.set(get_settings().session_cookie_name, token)


def test_no_cookie_returns_401(fresh_db):
    resp = TestClient(_app()).get("/who")
    assert resp.status_code == 401


def test_valid_cookie_returns_user(fresh_db):
    invited = service.invite(CreateUserInput(email="a@example.com", role="admin"))
    client = TestClient(_app())
    _set_session(client, invited.user.id, "admin")
    resp = client.get("/who")
    assert resp.status_code == 200
    assert resp.json() == {"id": invited.user.id, "role": "admin"}


def test_deactivated_user_returns_401(fresh_db):
    invited = service.invite(CreateUserInput(email="a@example.com"))
    repository.update_user(invited.user.id, {"is_active": 0})
    client = TestClient(_app())
    _set_session(client, invited.user.id, "user")
    resp = client.get("/who")
    assert resp.status_code == 401


def test_cookie_iat_before_sessions_valid_after_returns_401(fresh_db):
    invited = service.invite(CreateUserInput(email="a@example.com"))
    token = SessionSigner(get_settings()).issue(user_id=invited.user.id, role="user")
    repository.update_user(invited.user.id, {"sessions_valid_after": int(time.time()) + 60})
    client = TestClient(_app())
    client.cookies.set(get_settings().session_cookie_name, token)
    resp = client.get("/who")
    assert resp.status_code == 401


def test_missing_user_row_returns_401(fresh_db):
    client = TestClient(_app())
    _set_session(client, "11111111-1111-1111-1111-111111111111", "user")
    resp = client.get("/who")
    assert resp.status_code == 401
