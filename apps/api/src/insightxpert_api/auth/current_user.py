"""FastAPI dependency that resolves the caller to a User row.

Caching:
    In-process dict keyed by user_id, 30-second TTL. Eviction on user mutations
    lives alongside users.service writes via bump_session_cache(). Cross-process
    invalidation is out of scope at single-instance.

Guards (all 401):
    - no/invalid cookie
    - user row missing
    - user.is_active = 0
    - cookie.iat < user.sessions_valid_after
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request, status

from ..config import Settings, get_settings
from ..users import repository
from ..users.models import UserWithHash
from .session import SessionSigner

CACHE_TTL = 30

_cache: dict[str, tuple[UserWithHash, float]] = {}


def bump_session_cache(user_id: str) -> None:
    """Call from the service layer after any write to a users row."""
    _cache.pop(user_id, None)


def _cached_user(user_id: str) -> UserWithHash | None:
    now = time.time()
    hit = _cache.get(user_id)
    if hit is not None and now - hit[1] < CACHE_TTL:
        return hit[0]
    row = repository.get_by_id(user_id)
    if row is None:
        _cache.pop(user_id, None)
        return None
    _cache[user_id] = (row, now)
    return row


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    role: Literal["admin", "user"]


def _extract_token(request: Request, cookie_name: str) -> str | None:
    token = request.cookies.get(cookie_name)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    token = _extract_token(request, settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    claims = SessionSigner(settings).verify(token)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    row = _cached_user(claims.user_id)
    if row is None or not row.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    if claims.iat < row.sessions_valid_after:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return CurrentUser(id=row.id, email=row.email, role=row.role)


def require_admin(cu: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if cu.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return cu
