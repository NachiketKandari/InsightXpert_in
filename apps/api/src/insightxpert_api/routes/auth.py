"""Auth routes: login, logout, me, change-password."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from ..auth.current_user import CurrentUser, get_current_user
from ..auth.rate_limit import check_auth_rate_limit
from ..auth.session import SessionSigner
from ..config import Settings, get_settings
from ..users import service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# --- login ----------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    id: str
    email: EmailStr
    role: str
    must_change_password: bool


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=(settings.app_env != "local"),
        samesite="none" if settings.app_env != "local" else "lax",
        domain=settings.cookie_domain or None,
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    _rate_limit: None = Depends(check_auth_rate_limit),
) -> LoginResponse:
    user = service.authenticate(body.email, body.password)
    # DECISION(D-025): Flat error response shape {"detail": "message"} —
    # FastAPI's default. Not RFC 7807 Problem Details. Chosen for MVP simplicity.
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    # Ensure iat >= sessions_valid_after so the freshly-issued token is always valid.
    iat = max(int(time.time()), user.sessions_valid_after)
    token = SessionSigner(settings).issue(user_id=user.id, role=user.role, iat=iat)
    _set_session_cookie(response, settings, token)
    service.touch_last_seen(user.id)
    return LoginResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        must_change_password=user.must_change_password,
    )


# --- register -------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    _rate_limit: None = Depends(check_auth_rate_limit),
) -> LoginResponse:
    if not settings.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="registration is disabled",
        )
    try:
        user = service.register(body.email, body.password)
    except service.EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email_exists"
        ) from None
    except service.WeakPasswordError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from None
    iat = max(int(time.time()), user.sessions_valid_after)
    token = SessionSigner(settings).issue(user_id=user.id, role=user.role, iat=iat)
    _set_session_cookie(response, settings, token)
    service.touch_last_seen(user.id)
    return LoginResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        must_change_password=user.must_change_password,
    )


# --- logout ---------------------------------------------------------------


@router.post("/logout")
async def logout(response: Response, settings: Settings = Depends(get_settings)) -> dict[str, str]:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        domain=settings.cookie_domain or None,
        samesite="none" if settings.app_env != "local" else "lax",
        secure=(settings.app_env != "local"),
    )
    return {"status": "ok"}


# --- me -------------------------------------------------------------------


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    role: str
    is_active: bool
    must_change_password: bool
    onboarding_completed: bool = False


@router.get("/me", response_model=MeResponse)
async def me(cu: CurrentUser = Depends(get_current_user)) -> MeResponse:
    # CurrentUser already carries all the fields we need (fetched by the
    # dependency). No second DB query — saves 300-800ms on the critical
    # auth-gate path.
    return MeResponse(
        id=cu.id,
        email=cu.email,
        role=cu.role,
        is_active=cu.is_active,
        must_change_password=cu.must_change_password,
        onboarding_completed=cu.onboarding_completed,
    )


# --- onboarding-complete -------------------------------------------------


@router.post("/me/onboarding-complete")
async def complete_onboarding(
    cu: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    """Mark the current user's onboarding tour as completed."""
    from ..auth.current_user import bump_session_cache
    from ..users.repository import update_user

    update_user(cu.id, {"onboarding_completed": 1})
    bump_session_cache(cu.id)
    return {"status": "ok"}


# --- change-password ------------------------------------------------------


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    cu: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    try:
        service.change_password(cu.id, current=body.current_password, new=body.new_password)
    except service.InvalidCredentialsError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return {"status": "ok"}

