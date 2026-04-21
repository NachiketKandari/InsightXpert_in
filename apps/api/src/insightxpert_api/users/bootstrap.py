"""First-admin bootstrap. Runs once on app startup.

Semantics:
  - If any user already exists → skip (even if bootstrap env changed).
  - If BOOTSTRAP_ADMIN_EMAIL / _PASSWORD missing → skip silently.
  - Otherwise insert one admin with must_change_password=False (the admin
    chose this password themselves via env; no forced rotation).
"""

from __future__ import annotations

import time
import uuid

from ..config import get_settings
from ..logging import get_logger
from . import repository
from .hashing import hash_password
from .models import UserWithHash

log = get_logger("users.bootstrap")


def run() -> None:
    settings = get_settings()
    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password
    if not email or not password:
        log.info("bootstrap.skipped", reason="env_not_set")
        return
    if repository.list_users():
        log.info("bootstrap.skipped", reason="users_exist")
        return
    now = int(time.time())
    repository.insert_user(UserWithHash(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
        must_change_password=False,
        sessions_valid_after=now,
        created_at=now,
        updated_at=now,
        last_seen_at=None,
    ))
    log.info("bootstrap.applied", email=email)
