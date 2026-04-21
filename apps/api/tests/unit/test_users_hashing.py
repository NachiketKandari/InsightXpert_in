from __future__ import annotations

from insightxpert_api.users.hashing import hash_password, verify_password


def test_hash_then_verify_returns_true():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_wrong_password_is_false():
    h = hash_password("correct horse battery staple")
    assert verify_password("nope", h) is False


def test_verify_accepts_unicode():
    h = hash_password("пароль🔑")
    assert verify_password("пароль🔑", h) is True


def test_hash_is_nondeterministic():
    assert hash_password("same") != hash_password("same")


def test_verify_rejects_garbage_hash():
    assert verify_password("anything", "not-an-argon2-hash") is False
