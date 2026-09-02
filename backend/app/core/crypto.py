"""Symmetric encryption for secrets we must be able to read back.

Survey Solutions requires the actual password on every API call, so it cannot be
hashed. It is encrypted with a Fernet key held only in the environment.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    key = settings.encryption_key.strip()
    if not key:
        # Derive a stable key from SECRET_KEY so development setups work without
        # extra configuration. Production should always set ENCRYPTION_KEY.
        digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:  # pragma: no cover - config error
        raise RuntimeError(
            "ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
            "python -m app.cli gen-encryption-key"
        ) from exc


def encrypt(value: str) -> str:
    if value == "":
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError(
            "Stored secret could not be decrypted. The ENCRYPTION_KEY has probably "
            "changed since it was saved; re-enter the credentials."
        ) from exc


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")
