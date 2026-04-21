from __future__ import annotations

from insightxpert_api.users import bootstrap, repository, service
from insightxpert_api.users.models import CreateUserInput


def test_bootstrap_creates_admin_when_no_users(fresh_db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@insightxpert.ai")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin123")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()

    created = repository.get_by_email("admin@insightxpert.ai")
    assert created is not None
    assert created.role == "admin"
    assert service.authenticate("admin@insightxpert.ai", "admin123") is not None
    assert created.must_change_password is False


def test_bootstrap_creates_admin_and_user_when_both_env_set(fresh_db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@insightxpert.ai")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin123")
    monkeypatch.setenv("BOOTSTRAP_USER_EMAIL", "user@insightxpert.ai")
    monkeypatch.setenv("BOOTSTRAP_USER_PASSWORD", "user@insightxpert.ai123")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()

    admin = repository.get_by_email("admin@insightxpert.ai")
    assert admin is not None
    assert admin.role == "admin"
    assert service.authenticate("admin@insightxpert.ai", "admin123") is not None

    user = repository.get_by_email("user@insightxpert.ai")
    assert user is not None
    assert user.role == "user"
    assert service.authenticate("user@insightxpert.ai", "user@insightxpert.ai123") is not None

    assert len(repository.list_users()) == 2


def test_bootstrap_admin_only_when_user_env_missing(fresh_db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@insightxpert.ai")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin123")
    # monkeypatch the env vars directly rather than editing .env.local —
    # Pydantic Settings reads both, with env winning, so explicit empty strings
    # shadow any values the developer has in their local .env.local.
    monkeypatch.setenv("BOOTSTRAP_USER_EMAIL", "")
    monkeypatch.setenv("BOOTSTRAP_USER_PASSWORD", "")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()

    assert repository.get_by_email("admin@insightxpert.ai") is not None
    assert repository.get_by_email("user@insightxpert.ai") is None
    assert len(repository.list_users()) == 1


def test_bootstrap_is_idempotent(fresh_db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@insightxpert.ai")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin123")
    monkeypatch.setenv("BOOTSTRAP_USER_EMAIL", "user@insightxpert.ai")
    monkeypatch.setenv("BOOTSTRAP_USER_PASSWORD", "user@insightxpert.ai123")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()
    before = repository.list_users()
    bootstrap.run()
    after = repository.list_users()
    assert len(before) == 2
    assert len(after) == 2


def test_bootstrap_skips_when_other_users_exist(fresh_db, monkeypatch):
    service.invite(CreateUserInput(email="pre@example.com"))
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@insightxpert.ai")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin123")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()
    assert repository.get_by_email("admin@insightxpert.ai") is None


def test_bootstrap_noop_when_env_absent(fresh_db, monkeypatch):
    # Shadow any .env.local bootstrap values with empty strings so pydantic_settings
    # treats them as falsy — simulating no bootstrap env configured.
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    monkeypatch.setenv("BOOTSTRAP_USER_EMAIL", "")
    monkeypatch.setenv("BOOTSTRAP_USER_PASSWORD", "")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()
    assert repository.list_users() == []
