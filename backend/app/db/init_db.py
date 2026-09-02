"""Schema creation and first-boot bootstrapping."""

from __future__ import annotations

from sqlalchemy import inspect, select, text
from sqlalchemy.schema import CreateColumn

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Role, User  # noqa: F401 - registers every table

logger = get_logger(__name__)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema is up to date")


def ensure_columns() -> None:
    """Add columns the models declare but an existing database lacks.

    create_all creates missing tables and never touches existing ones, so an
    upgrade in place would silently run without any newly added column and fail
    at the first query that used it. This covers the additive case, which is the
    only kind of change the schema has needed. Dropping, renaming or retyping a
    column still needs a real migration.
    """
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            if not column.nullable and column.server_default is None:
                # Adding this to a table with rows in it would fail; say so
                # rather than crashing the whole start-up.
                logger.error(
                    "Column %s.%s is missing and cannot be added automatically "
                    "because it is NOT NULL with no server default.",
                    table.name,
                    column.name,
                )
                continue
            definition = CreateColumn(column).compile(dialect=engine.dialect)
            with engine.begin() as connection:
                connection.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN {definition}')
                )
            logger.info("Added missing column %s.%s", table.name, column.name)


def create_first_admin() -> None:
    """Create the bootstrap administrator, but only when no users exist."""
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)) is not None:
            return
        email = settings.first_admin_email.lower()
        admin = User(
            email=email,
            full_name=settings.first_admin_name,
            role=Role.admin,
            is_active=True,
            hashed_password=hash_password(settings.first_admin_password),
        )
        db.add(admin)
        db.commit()
        logger.info("Created the first administrator account: %s", email)
        if settings.first_admin_password in ("changeme", "CHANGE-ME-strong-password"):
            logger.warning(
                "The bootstrap administrator is using the default password. "
                "Sign in and change it immediately."
            )


def initialise() -> None:
    settings.ensure_directories()
    create_tables()
    ensure_columns()
    create_first_admin()
