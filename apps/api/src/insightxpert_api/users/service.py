"""Users service - business logic. Never touches SQLAlchemy directly."""

from __future__ import annotations

import secrets
import time
import uuid

import sqlalchemy.exc

from ..auth.current_user import bump_session_cache
from . import repository
from .hashing import hash_password, verify_password
from .models import CreateUserInput, InviteResult, Role, User, UserWithHash


class UsersServiceError(Exception):
    pass


class EmailAlreadyExistsError(UsersServiceError):
    pass


class WeakPasswordError(UsersServiceError):
    pass


class InvalidCredentialsError(UsersServiceError):
    pass


class UserNotFoundError(UsersServiceError):
    pass


class LastAdminError(UsersServiceError):
    """Guard: can't delete, demote, or deactivate the final active admin."""


def _now() -> int:
    return int(time.time())


def _gen_temp_password() -> str:
    # 18 bytes url-safe base64 ~= 24 chars
    return secrets.token_urlsafe(18)


def _to_public(u: UserWithHash) -> User:
    return User(**u.model_dump(exclude={"password_hash"}))


def invite(input: CreateUserInput) -> InviteResult:
    temp = input.temp_password or _gen_temp_password()
    now = _now()
    row = UserWithHash(
        id=str(uuid.uuid4()),
        email=input.email,
        password_hash=hash_password(temp),
        role=input.role,
        is_active=True,
        must_change_password=True,
        sessions_valid_after=now,
        created_at=now,
        updated_at=now,
        last_seen_at=None,
    )
    try:
        repository.insert_user(row)
    except sqlalchemy.exc.IntegrityError as e:
        raise EmailAlreadyExistsError(input.email) from e
    return InviteResult(user=_to_public(row), temp_password=temp)


def register(email: str, password: str) -> User:
    if len(password) < 8:
        raise WeakPasswordError("Password must be at least 8 characters")
    existing = repository.get_by_email(email)
    if existing is not None:
        raise EmailAlreadyExistsError(email)
    now = _now()
    row = UserWithHash(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        must_change_password=False,
        sessions_valid_after=now,
        created_at=now,
        updated_at=now,
        last_seen_at=None,
    )
    try:
        repository.insert_user(row)
    except sqlalchemy.exc.IntegrityError:
        raise EmailAlreadyExistsError(email)
    return _to_public(row)


def authenticate(email: str, password: str) -> User | None:
    row = repository.get_by_email(email)
    if row is None or not row.is_active:
        return None
    if not verify_password(password, row.password_hash):
        return None
    return _to_public(row)


def change_password(user_id: str, current: str, new: str) -> None:
    row = repository.get_by_id(user_id)
    if row is None:
        raise UserNotFoundError(user_id)
    if not verify_password(current, row.password_hash):
        raise InvalidCredentialsError()
    now = _now()
    # sessions_valid_after = now + 1 ensures any token issued at `now`
    # (iat == now) satisfies iat < sessions_valid_after and is rejected.
    repository.update_user(user_id, {
        "password_hash": hash_password(new),
        "must_change_password": 0,
        "sessions_valid_after": now + 1,
        "updated_at": now,
    })
    bump_session_cache(user_id)


def reset_password(user_id: str) -> str:
    if repository.get_by_id(user_id) is None:
        raise UserNotFoundError(user_id)
    temp = _gen_temp_password()
    now = _now()
    # sessions_valid_after = now + 1 ensures any token issued at `now`
    # (iat == now) satisfies iat < sessions_valid_after and is rejected.
    repository.update_user(user_id, {
        "password_hash": hash_password(temp),
        "must_change_password": 1,
        "sessions_valid_after": now + 1,
        "updated_at": now,
    })
    bump_session_cache(user_id)
    return temp


def set_role(user_id: str, role: Role) -> None:
    row = repository.get_by_id(user_id)
    if row is None:
        raise UserNotFoundError(user_id)
    if row.role == "admin" and role == "user":
        if repository.count_active_admins() <= 1:
            raise LastAdminError()
    now = _now()
    repository.update_user(user_id, {
        "role": role,
        "sessions_valid_after": now,
        "updated_at": now,
    })
    bump_session_cache(user_id)


def set_active(user_id: str, active: bool) -> None:
    row = repository.get_by_id(user_id)
    if row is None:
        raise UserNotFoundError(user_id)
    if row.role == "admin" and not active and repository.count_active_admins() <= 1:
        raise LastAdminError()
    now = _now()
    repository.update_user(user_id, {
        "is_active": 1 if active else 0,
        "sessions_valid_after": now,
        "updated_at": now,
    })
    bump_session_cache(user_id)


def delete(user_id: str) -> None:
    row = repository.get_by_id(user_id)
    if row is None:
        raise UserNotFoundError(user_id)
    if row.role == "admin" and repository.count_active_admins() <= 1:
        raise LastAdminError()
    bump_session_cache(user_id)
    repository.delete_user(user_id)


def touch_last_seen(user_id: str) -> None:
    repository.update_user(user_id, {"last_seen_at": _now()})
    bump_session_cache(user_id)


def get_public(user_id: str) -> User | None:
    row = repository.get_by_id(user_id)
    return _to_public(row) if row is not None else None
