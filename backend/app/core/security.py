"""Password hashing, JWT issuing and API-key helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

_MAX_BCRYPT_BYTES = 72


def _prepare(password: str) -> bytes:
    """bcrypt silently truncates past 72 bytes; pre-hash so long passwords stay unique."""
    raw = password.encode("utf-8")
    if len(raw) > _MAX_BCRYPT_BYTES:
        raw = hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str, extra: dict[str, Any] | None = None, expires_minutes: int | None = None
) -> str:
    expire_delta = dt.timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + expire_delta).timestamp()),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Raise jwt.PyJWTError subclasses on invalid/expired tokens."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


API_KEY_PREFIX = "shq"


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, hashed_key). The full key is shown once."""
    body = secrets.token_urlsafe(32)
    prefix = secrets.token_hex(4)
    full = f"{API_KEY_PREFIX}_{prefix}_{body}"
    return full, prefix, hash_api_key(full)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_public_token() -> str:
    return secrets.token_urlsafe(24)
