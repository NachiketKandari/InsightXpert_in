"""First-admin bootstrap. Runs once on app startup.

Semantics:
  - If any user already exists → skip the whole bootstrap (even if bootstrap
    env changed). This includes skipping the regular user seed. The rationale
    is that the admin (or any user) might have been created manually after the
    first boot, and we should not re-create on subsequent startups.
  - If BOOTSTRAP_ADMIN_EMAIL / _PASSWORD missing → skip silently.
  - Otherwise insert admin with must_change_password=False (the admin chose
    this password themselves via env; no forced rotation).
  - If BOOTSTRAP_USER_EMAIL / _PASSWORD are also set, insert a regular user
    alongside the admin (same idempotence: skipped if any user already exists).
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


def _insert_bootstrap_user(email: str, password: str, role: str) -> None:
    now = int(time.time())
    repository.insert_user(UserWithHash(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_change_password=False,
        sessions_valid_after=now,
        created_at=now,
        updated_at=now,
        last_seen_at=None,
    ))


def run() -> None:
    settings = get_settings()
    if repository.list_users():
        log.info("bootstrap.skipped", reason="users_exist")
        return

    admin_email = settings.bootstrap_admin_email
    admin_pw = settings.bootstrap_admin_password
    user_email = settings.bootstrap_user_email
    user_pw = settings.bootstrap_user_password

    if not admin_email or not admin_pw:
        log.info("bootstrap.skipped", reason="admin_env_not_set")
        return

    _insert_bootstrap_user(admin_email, admin_pw, role="admin")
    log.info("bootstrap.applied", email=admin_email, role="admin")

    if user_email and user_pw:
        _insert_bootstrap_user(user_email, user_pw, role="user")
        log.info("bootstrap.applied", email=user_email, role="user")
