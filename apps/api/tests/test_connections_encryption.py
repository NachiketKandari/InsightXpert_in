"""Round-trip + tamper + missing-key tests for connections.encryption."""

from __future__ import annotations

import pytest

from insightxpert_api.config import get_settings


_TEST_KEY = "GbhRElFcz5W3rC9V8a4GQYoT3p6jZCqZ4EQRQyGzwYY="


def test_round_trip(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", _TEST_KEY)
    get_settings.cache_clear()
    from insightxpert_api.connections.encryption import decrypt, encrypt

    plaintext = "host=db.example.com user=ro password=hunter2"
    cipher = encrypt(plaintext)
    assert cipher != plaintext
    assert decrypt(cipher) == plaintext


def test_decrypt_rejects_tampered(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", _TEST_KEY)
    get_settings.cache_clear()
    from insightxpert_api.connections.encryption import decrypt, encrypt

    cipher = encrypt("ok")
    tampered = cipher[:-4] + "AAAA"
    with pytest.raises(Exception):
        decrypt(tampered)


def test_missing_key_raises(monkeypatch):
    from insightxpert_api.config import Settings
    from insightxpert_api.connections.encryption import _get_fernet

    settings = Settings()
    settings.credential_encryption_key = None
    monkeypatch.setattr("insightxpert_api.connections.encryption.get_settings", lambda: settings)

    with pytest.raises(ValueError, match="CREDENTIAL_ENCRYPTION_KEY"):
        _get_fernet()
