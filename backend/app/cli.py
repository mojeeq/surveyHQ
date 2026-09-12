"""Small operational commands: python -m app.cli <command>."""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.crypto import generate_key
from app.core.security import hash_password
from app.db.init_db import initialise
from app.db.session import SessionLocal
from app.models import Role, User


def gen_encryption_key() -> None:
    print(generate_key())


def init_database() -> None:
    initialise()
    print("Database initialised.")


def create_admin() -> None:
    if len(sys.argv) < 4:
        print("Usage: python -m app.cli create-admin <email> <password> [full name]")
        raise SystemExit(2)
    email, password = sys.argv[2].lower(), sys.argv[3]
    full_name = sys.argv[4] if len(sys.argv) > 4 else "Administrator"
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            existing.hashed_password = hash_password(password)
            existing.role = Role.admin
            existing.is_active = True
            db.commit()
            print(f"Updated existing user {email} to administrator with a new password.")
            return
        db.add(
            User(
                email=email,
                full_name=full_name,
                role=Role.admin,
                hashed_password=hash_password(password),
            )
        )
        db.commit()
        print(f"Created administrator {email}.")


def reset_password() -> None:
    if len(sys.argv) < 4:
        print("Usage: python -m app.cli reset-password <email> <new password>")
        raise SystemExit(2)
    email, password = sys.argv[2].lower(), sys.argv[3]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"No user found with the email {email}.")
            raise SystemExit(1)
        user.hashed_password = hash_password(password)
        db.commit()
        print(f"Password reset for {email}.")


COMMANDS = {
    "gen-encryption-key": gen_encryption_key,
    "init-db": init_database,
    "create-admin": create_admin,
    "reset-password": reset_password,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Available commands:")
        for name in COMMANDS:
            print(f"  {name}")
        raise SystemExit(2)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
