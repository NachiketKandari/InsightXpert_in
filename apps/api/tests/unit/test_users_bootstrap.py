from __future__ import annotations

from insightxpert_api.users import bootstrap, repository, service
from insightxpert_api.users.models import CreateUserInput


def test_bootstrap_creates_admin_when_no_users(fresh_db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "boot@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "boot-strap-pw-12345")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()

    created = repository.get_by_email("boot@example.com")
    assert created is not None
    assert created.role == "admin"
    assert service.authenticate("boot@example.com", "boot-strap-pw-12345") is not None
    assert created.must_change_password is False


def test_bootstrap_is_idempotent(fresh_db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "boot@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "boot-strap-pw-12345")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()
    before = repository.list_users()
    bootstrap.run()
    after = repository.list_users()
    assert len(before) == 1
    assert len(after) == 1


def test_bootstrap_skips_when_other_users_exist(fresh_db, monkeypatch):
    service.invite(CreateUserInput(email="pre@example.com"))
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "boot@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "boot-strap-pw-12345")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()
    assert repository.get_by_email("boot@example.com") is None


def test_bootstrap_noop_when_env_absent(fresh_db, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    bootstrap.run()
    assert repository.list_users() == []
