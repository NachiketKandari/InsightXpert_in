"""Fernet-based encryption for stored DB connection credentials.

Key is read from ``CREDENTIAL_ENCRYPTION_KEY`` (32 bytes, base64-encoded).
Generate with::

    python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

Rotation: re-encrypt all rows with the new key, then update env. No automated
rotation in v1.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from ..config import Settings, get_settings


def _get_fernet(settings: Settings | None = None) -> Fernet:
    s = settings or get_settings()
    if not s.credential_encryption_key:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY is required for connection storage"
        )
    return Fernet(s.credential_encryption_key.encode())


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
