from __future__ import annotations

import pytest

from insightxpert_api.users import repository, service
from insightxpert_api.users.models import CreateUserInput


def test_invite_creates_active_user_with_must_change_password_flag(fresh_db):
    result = service.invite(CreateUserInput(email="alice@example.com", role="user"))
    assert result.user.email == "alice@example.com"
    assert result.user.role == "user"
    assert result.user.is_active is True
    assert result.user.must_change_password is True
    assert len(result.temp_password) >= 12


def test_invite_uses_supplied_temp_password_if_given(fresh_db):
    result = service.invite(CreateUserInput(
        email="bob@example.com", role="admin", temp_password="supplied-by-admin-pw-12345",
    ))
    assert result.temp_password == "supplied-by-admin-pw-12345"


def test_invite_duplicate_email_raises(fresh_db):
    service.invite(CreateUserInput(email="a@example.com"))
    with pytest.raises(service.EmailAlreadyExistsError):
        service.invite(CreateUserInput(email="A@Example.COM"))


def test_authenticate_correct_password_returns_user(fresh_db):
    invited = service.invite(CreateUserInput(email="ok@example.com"))
    user = service.authenticate("ok@example.com", invited.temp_password)
    assert user is not None
    assert user.id == invited.user.id


def test_authenticate_wrong_password_returns_none(fresh_db):
    service.invite(CreateUserInput(email="ok@example.com"))
    assert service.authenticate("ok@example.com", "wrong") is None


def test_authenticate_inactive_user_returns_none(fresh_db):
    invited = service.invite(CreateUserInput(email="ok@example.com"))
    repository.update_user(invited.user.id, {"is_active": 0})
    assert service.authenticate("ok@example.com", invited.temp_password) is None


def test_change_password_updates_hash_and_clears_flag_and_bumps_sva(fresh_db):
    invited = service.invite(CreateUserInput(email="ok@example.com"))
    before = repository.get_by_id(invited.user.id)
    assert before is not None
    service.change_password(invited.user.id, current=invited.temp_password, new="a-new-secure-pw-99")
    after = repository.get_by_id(invited.user.id)
    assert after is not None
    assert after.password_hash != before.password_hash
    assert after.must_change_password is False
    assert after.sessions_valid_after >= before.sessions_valid_after


def test_change_password_wrong_current_raises(fresh_db):
    invited = service.invite(CreateUserInput(email="ok@example.com"))
    with pytest.raises(service.InvalidCredentialsError):
        service.change_password(invited.user.id, current="wrong", new="other-pw-1234")


def test_reset_password_returns_temp_and_sets_flag(fresh_db):
    invited = service.invite(CreateUserInput(email="ok@example.com"))
    service.change_password(invited.user.id, current=invited.temp_password, new="some-strong-pw-99")
    reset_temp = service.reset_password(invited.user.id)
    fresh = repository.get_by_id(invited.user.id)
    assert fresh is not None
    assert fresh.must_change_password is True
    assert service.authenticate("ok@example.com", "some-strong-pw-99") is None
    assert service.authenticate("ok@example.com", reset_temp) is not None


def test_delete_last_admin_raises(fresh_db):
    admin = service.invite(CreateUserInput(email="only@example.com", role="admin"))
    with pytest.raises(service.LastAdminError):
        service.delete(admin.user.id)


def test_delete_non_last_admin_is_allowed(fresh_db):
    a = service.invite(CreateUserInput(email="a@example.com", role="admin"))
    service.invite(CreateUserInput(email="b@example.com", role="admin"))
    service.delete(a.user.id)
    assert repository.get_by_id(a.user.id) is None


def test_demote_last_admin_raises(fresh_db):
    admin = service.invite(CreateUserInput(email="only@example.com", role="admin"))
    with pytest.raises(service.LastAdminError):
        service.set_role(admin.user.id, "user")


def test_touch_last_seen_updates_column(fresh_db):
    invited = service.invite(CreateUserInput(email="t@example.com"))
    service.touch_last_seen(invited.user.id)
    fresh = repository.get_by_id(invited.user.id)
    assert fresh is not None and fresh.last_seen_at is not None


# --- register -----------------------------------------------------------


def test_register_creates_active_user_without_must_change_password(fresh_db):
    user = service.register("newuser@example.com", "securepassword")
    assert user.email == "newuser@example.com"
    assert user.role == "user"
    assert user.is_active is True
    assert user.must_change_password is False


def test_register_duplicate_email_raises(fresh_db):
    service.register("dup@example.com", "securepassword")
    with pytest.raises(service.EmailAlreadyExistsError):
        service.register("DUP@example.com", "anotherpassword")


def test_register_short_password_raises(fresh_db):
    with pytest.raises(service.WeakPasswordError, match="at least 8"):
        service.register("ok@example.com", "short")


def test_register_and_authenticate(fresh_db):
    service.register("authme@example.com", "mypassword123")
    user = service.authenticate("authme@example.com", "mypassword123")
    assert user is not None
    assert user.email == "authme@example.com"


def test_register_and_authenticate_wrong_password(fresh_db):
    service.register("authme2@example.com", "correctpass")
    assert service.authenticate("authme2@example.com", "wrongpass") is None
