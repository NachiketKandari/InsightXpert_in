"""Session token signer. One anonymous session per browser; no user accounts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import Settings


@dataclass(frozen=True)
class SessionClaims:
    """What we extract from a valid session token."""

    session_id: str


class SessionSigner:
    """Issue + verify signed session tokens. Carries only an opaque session_id."""

    _SALT = "ix-session"

    def __init__(self, settings: Settings) -> None:
        self._serializer = URLSafeTimedSerializer(settings.session_secret, salt=self._SALT)
        self._ttl = settings.session_ttl_seconds

    def issue(self) -> str:
        """Mint a new token bound to a fresh uuid4."""
        return self._serializer.dumps({"session_id": str(uuid.uuid4())})

    def verify(self, token: str) -> SessionClaims | None:
        """Return claims if the token is valid + unexpired, else None."""
        try:
            data = self._serializer.loads(token, max_age=self._ttl)
        except (BadSignature, SignatureExpired):
            return None
        session_id = data.get("session_id") if isinstance(data, dict) else None
        if not isinstance(session_id, str):
            return None
        return SessionClaims(session_id=session_id)
