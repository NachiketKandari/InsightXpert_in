"""Auth routes: unlock (password gate), me, logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from ..auth.dependencies import require_session
from ..auth.session import SessionClaims, SessionSigner
from ..config import Settings, get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class UnlockRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class UnlockResponse(BaseModel):
    status: str


class MeResponse(BaseModel):
    session_id: str


@router.post("/unlock", response_model=UnlockResponse)
async def unlock(
    body: UnlockRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> UnlockResponse:
    """Exchange the shared password for a signed session cookie."""
    if body.password != settings.gate_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    token = SessionSigner(settings).issue()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=(settings.app_env != "local"),
        samesite="lax",
        path="/",
    )
    return UnlockResponse(status="ok")


@router.get("/me", response_model=MeResponse)
async def me(claims: SessionClaims = Depends(require_session)) -> MeResponse:
    """Return the caller's session_id. Handy for FE bootstrap."""
    return MeResponse(session_id=claims.session_id)


@router.post("/logout", response_model=UnlockResponse)
async def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> UnlockResponse:
    response.delete_cookie(settings.session_cookie_name, path="/")
    return UnlockResponse(status="ok")
