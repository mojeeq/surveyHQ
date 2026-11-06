"""Usernames and account identity helpers.

Email remains the recovery/contact identity. Usernames are the short public
handle people use to sign in and share projects without exposing the global
user directory.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")


def normalize_username(value: str) -> str:
    """Return the canonical form stored and compared by SurveyHQ."""
    return value.strip().lower()


def validate_username(value: str) -> str:
    """Normalize and validate a public username.

    Keeping the alphabet deliberately small makes handles easy to type, safe in
    URLs, and unambiguous when a project owner adds somebody by username.
    """
    username = normalize_username(value)
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Username must be 3-32 characters, start with a letter or number, "
            "and contain only letters, numbers, dots, underscores or hyphens"
        )
    return username


def username_from_email(email: str) -> str:
    """Make a safe seed for legacy/admin-created accounts from an email address."""
    local = email.split("@", 1)[0].lower()
    local = re.sub(r"[^a-z0-9._-]+", "-", local).strip("._-")
    if not local:
        local = "user"
    if not local[0].isalnum():
        local = f"user-{local}"
    if len(local) < USERNAME_MIN_LENGTH:
        local = f"user-{local}"
    return local[:USERNAME_MAX_LENGTH].rstrip("._-") or "user"


def username_taken(db: Session, username: str, *, exclude_user_id: str | None = None) -> bool:
    statement = select(User.id).where(User.username == normalize_username(username))
    if exclude_user_id:
        statement = statement.where(User.id != exclude_user_id)
    return db.scalar(statement) is not None


def next_available_username(db: Session, seed: str) -> str:
    """Return a deterministic unique username, adding -2, -3, ... as needed."""
    base = username_from_email(seed) if "@" in seed else normalize_username(seed)
    if not base:
        base = "user"
    candidate = base[:USERNAME_MAX_LENGTH]
    counter = 2
    while username_taken(db, candidate):
        suffix = f"-{counter}"
        candidate = f"{base[: USERNAME_MAX_LENGTH - len(suffix)]}{suffix}"
        counter += 1
    return candidate
