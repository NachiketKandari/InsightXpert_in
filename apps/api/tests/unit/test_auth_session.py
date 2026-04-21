from __future__ import annotations

import itsdangerous

from insightxpert_api.auth.session import SessionClaims, SessionSigner
from insightxpert_api.config import Settings


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        gate_password="ignored",
        session_secret="secret-for-tests-secret-for-tests",
        session_cookie_name="ix_session",
        gemini_api_key="k",
    )


def test_issue_and_verify_roundtrip():
    s = SessionSigner(_settings())
    token = s.issue(user_id="u1", role="admin", sid="aaaaaaaa")
    claims = s.verify(token)
    assert claims is not None
    assert claims.user_id == "u1"
    assert claims.role == "admin"
    assert claims.sid == "aaaaaaaa"
    assert isinstance(claims.iat, int) and claims.iat > 0


def test_tampered_token_fails_verification():
    s = SessionSigner(_settings())
    token = s.issue(user_id="u1", role="user", sid="aaaaaaaa")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert s.verify(tampered) is None


def test_legacy_token_without_user_id_is_rejected():
    """Pre-B1 tokens (session_id only, no user_id) must fail verification now.

    After B1 we don't support anonymous sessions, so a pre-B1 token must 401
    the next request even if it's unexpired.
    """
    legacy = itsdangerous.URLSafeTimedSerializer(
        "secret-for-tests-secret-for-tests", salt="ix-session"
    ).dumps({"session_id": "legacy-session-id", "iat": 1700000000.0})

    assert SessionSigner(_settings()).verify(legacy) is None
