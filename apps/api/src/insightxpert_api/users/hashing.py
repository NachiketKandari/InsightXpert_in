"""Argon2id password hashing. Uses library defaults — they're conservative.

verify_password is the only safe way to check a password; it is constant-time
and handles malformed hashes by returning False rather than raising.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

# DECISION(D-051): Argon2id password hashing (not bcrypt) — memory-hard, GPU/ASIC-resistant
_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
