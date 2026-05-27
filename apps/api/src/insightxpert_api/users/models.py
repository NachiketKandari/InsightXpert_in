"""Pydantic DTOs for the users domain.

Separating DTOs from the Table keeps Pydantic validation out of the DB layer
and lets routes/tests consume stable types independent of SQLAlchemy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Role = Literal["admin", "user"]


class User(BaseModel):
    """Public shape. Never includes password_hash."""
    id: str
    email: EmailStr
    role: Role
    is_active: bool
    must_change_password: bool
    onboarding_completed: bool = False
    sessions_valid_after: int
    created_at: int
    updated_at: int
    last_seen_at: int | None = None


class UserWithHash(User):
    """Internal shape used inside the service layer only."""
    password_hash: str


class CreateUserInput(BaseModel):
    email: EmailStr
    role: Role = "user"
    temp_password: str | None = Field(default=None, min_length=12, max_length=256)


class InviteResult(BaseModel):
    """Returned once, never again, to the admin who invited the user."""
    user: User
    temp_password: str
