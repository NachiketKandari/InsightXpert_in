"""FastAPI dependencies for session-gated endpoints."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from ..config import Settings, get_settings
from .session import SessionClaims, SessionSigner


def _extract_token(request: Request, cookie_name: str) -> str | None:
    token = request.cookies.get(cookie_name)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def require_session(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SessionClaims:
    """Require a valid session token. Raises 401 (missing) or 403 (bad/expired)."""
    token = _extract_token(request, settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    claims = SessionSigner(settings).verify(token)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return claims
