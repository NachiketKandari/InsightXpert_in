"""Admin user-management routes.

All endpoints gated by :func:`require_admin`. Service-layer calls are wrapped in
``asyncio.to_thread`` so the event loop stays responsive; argon2 hashing + the
``users.repository`` SQL are both blocking today.

Surface (per spec §5.2):
    GET     /api/v1/admin/users/                       — list users
    POST    /api/v1/admin/users/                       — invite (returns temp_password once)
    PATCH   /api/v1/admin/users/{user_id}              — mutate role / is_active
    POST    /api/v1/admin/users/{user_id}/reset-password — rotate temp_password
    DELETE  /api/v1/admin/users/{user_id}              — delete

Error translation mirrors the users.service exceptions:
    EmailAlreadyExistsError → 409 email_exists
    UserNotFoundError       → 404 not_found
    LastAdminError          → 409 last_admin
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from ..auth.current_user import CurrentUser, require_admin
from ..users import repository, service
from ..users.models import CreateUserInput, Role

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin-users"])


class ListItem(BaseModel):
    id: str
    email: EmailStr
    role: str
    is_active: bool
    must_change_password: bool
    last_seen_at: int | None


class InviteResponse(BaseModel):
    id: str
    email: EmailStr
    role: str
    temp_password: str


class PatchUser(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class ResetPasswordResponse(BaseModel):
    temp_password: str


@router.get("/", response_model=list[ListItem])
async def list_users(cu: CurrentUser = Depends(require_admin)) -> list[ListItem]:
    rows = await asyncio.to_thread(repository.list_users)
    return [
        ListItem(
            id=r.id,
            email=r.email,
            role=r.role,
            is_active=r.is_active,
            must_change_password=r.must_change_password,
            last_seen_at=r.last_seen_at,
        )
        for r in rows
    ]


@router.post("/", response_model=InviteResponse)
async def invite(
    body: CreateUserInput,
    cu: CurrentUser = Depends(require_admin),
) -> InviteResponse:
    try:
        result = await asyncio.to_thread(service.invite, body)
    except service.EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email_exists"
        ) from None
    return InviteResponse(
        id=result.user.id,
        email=result.user.email,
        role=result.user.role,
        temp_password=result.temp_password,
    )


@router.patch("/{user_id}")
async def patch_user(
    user_id: str,
    body: PatchUser,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, str]:
    try:
        if body.role is not None:
            await asyncio.to_thread(service.set_role, user_id, body.role)
        if body.is_active is not None:
            await asyncio.to_thread(service.set_active, user_id, body.is_active)
    except service.UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not_found"
        ) from None
    except service.LastAdminError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="last_admin"
        ) from None
    return {"status": "ok"}


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    user_id: str,
    cu: CurrentUser = Depends(require_admin),
) -> ResetPasswordResponse:
    try:
        temp = await asyncio.to_thread(service.reset_password, user_id)
    except service.UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not_found"
        ) from None
    return ResetPasswordResponse(temp_password=temp)


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, str]:
    try:
        await asyncio.to_thread(service.delete, user_id)
    except service.UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not_found"
        ) from None
    except service.LastAdminError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="last_admin"
        ) from None
    return {"status": "ok"}


class _SharingDisabledBody(BaseModel):
    disabled: bool


@router.patch("/{user_id}/sharing-disabled")
async def set_user_sharing_disabled(
    user_id: str,
    body: _SharingDisabledBody,
    cu: CurrentUser = Depends(require_admin),
) -> dict:
    """Admin toggle for the per-user share kill-switch."""
    from sqlalchemy import update as sa_update

    from ..db.engine import get_engine
    from ..users.table import users

    def _update() -> int:
        with get_engine().begin() as conn:
            result = conn.execute(
                sa_update(users)
                .where(users.c.id == user_id)
                .values(sharing_disabled=1 if body.disabled else 0)
            )
            return result.rowcount

    rowcount = await asyncio.to_thread(_update)
    if rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"id": user_id, "sharing_disabled": body.disabled}
