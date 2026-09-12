"""Username migration behaviour for installations created before signup existed."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.db.init_db import create_tables, ensure_usernames
from app.db.session import SessionLocal, engine
from app.models import Role, User

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="The production upgrade path is exercised against PostgreSQL.",
)


def test_existing_accounts_receive_unique_usernames_before_the_new_index() -> None:
    create_tables()
    emails = ["legacy.same@example.com", "legacy.same@another.example"]
    with SessionLocal() as db:
        db.execute(delete(User).where(User.email.in_(emails)))
        db.add_all(
            [
                User(
                    email=email,
                    username=None,
                    full_name="Legacy user",
                    role=Role.viewer,
                    hashed_password="not-used-by-this-test",
                )
                for email in emails
            ]
        )
        db.commit()

    ensure_usernames()

    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.email.in_(emails)).order_by(User.email)))
        usernames = {user.username for user in users}
        assert len(usernames) == 2
        assert None not in usernames
        assert all(username and username.startswith("legacy.same") for username in usernames)
        db.execute(delete(User).where(User.email.in_(emails)))
        db.commit()
