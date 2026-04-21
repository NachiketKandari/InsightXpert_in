"""Signed session tokens carrying user identity.

Cookie payload: {user_id, role, iat, sid}. `sid` is an opaque random string
so rapid re-issue yields a byte-different cookie. `iat` is an int (seconds)
rather than float for easy comparison against users.sessions_valid_after.

Pre-B1 tokens (which carried {session_id, iat}) are explicitly rejected here
so the switch to real auth is atomic — no anonymous carryover sessions.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Literal

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import Settings

Role = Literal["admin", "user"]


@dataclass(frozen=True)
class SessionClaims:
    user_id: str
    role: Role
    iat: int
    sid: str


class SessionSigner:
    _SALT = "ix-session"

    def __init__(self, settings: Settings) -> None:
        self._serializer = URLSafeTimedSerializer(settings.session_secret, salt=self._SALT)
        self._ttl = settings.session_ttl_seconds

    def issue(self, *, user_id: str, role: Role, sid: str | None = None) -> str:
        payload = {
            "user_id": user_id,
            "role": role,
            "iat": int(time.time()),
            "sid": sid or secrets.token_urlsafe(8),
        }
        return self._serializer.dumps(payload)

    def verify(self, token: str) -> SessionClaims | None:
        try:
            data = self._serializer.loads(token, max_age=self._ttl)
        except (BadSignature, SignatureExpired):
            return None
        if not isinstance(data, dict):
            return None
        user_id = data.get("user_id")
        role = data.get("role")
        iat = data.get("iat")
        sid = data.get("sid")
        if (
            not isinstance(user_id, str)
            or role not in ("admin", "user")
            or not isinstance(iat, int)
            or not isinstance(sid, str)
        ):
            return None
        return SessionClaims(user_id=user_id, role=role, iat=iat, sid=sid)
