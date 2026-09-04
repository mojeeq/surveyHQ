"""Schema creation and first-boot bootstrapping."""

from __future__ import annotations

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateColumn, CreateIndex

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


def ensure_indexes() -> None:
    """Create indexes the models declare but an existing database lacks.

    ALTER TABLE ADD COLUMN adds the column and nothing else, so every index
    declared on a column that reached a live database that way is missing -
    including the unique ones. That is not only slow. A unique index is a
    constraint: without it, two requests can each check that a hostname is free
    and then both take it. The Python check in set_hostname exists because of
    exactly this gap; this closes it at the database, where it belongs.

    Only indexes are created here. A unique constraint declared as a table
    argument rather than on the column is left alone, because adding one to a
    table that already violates it fails, and there is no safe automatic answer
    to which of the duplicate rows should go.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {index["name"] for index in inspector.get_indexes(table.name)}
        # A unique column is served by a unique constraint on some backends and
        # by an index on others; either way the name is taken and reusing it
        # would fail, so both count as present.
        present |= {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(table.name)
        }
        for index in table.indexes:
            if index.name in present:
                continue
            statement = str(CreateIndex(index).compile(dialect=engine.dialect))
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement))
            except SQLAlchemyError as exc:
                # A unique index over rows that already violate it cannot be
                # created. Report which one and carry on: the rest of the
                # schema, and the application, are still fine without it.
                logger.error(
                    "Could not create index %s on %s: %s", index.name, table.name, exc
                )
                continue
            logger.info("Created missing index %s on %s", index.name, table.name)


def ensure_enum_values() -> None:
    """Add enum members the models declare but a PostgreSQL type lacks.

    create_all creates a missing type and never alters an existing one, so a new
    member reaches the database only as a runtime failure:

        invalid input value for enum chart_type: "crosstab"

    Nothing else catches this. SQLite stores enums as text and cannot reproduce
    it, and a database built from scratch already has every member, so it
    appears only when an existing deployment is upgraded - which is the case
    this whole function exists for.
    """
    if engine.dialect.name != "postgresql":
        return

    wanted: dict[str, list[str]] = {}
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            type_name = getattr(column.type, "name", None)
            # Enum.enums is the list of labels SQLAlchemy will actually send. It
            # is the names by default, not the values, and honours a
            # values_callable if one is ever set. Deriving the list from the
            # Python enum instead gets ExportFormat wrong - the database holds
            # "stata" while the member's value is "STATA" - and since this
            # function only ever adds, a wrong list adds junk labels that
            # PostgreSQL will not let you remove.
            labels = getattr(column.type, "enums", None)
            if not type_name or not labels:
                continue
            wanted.setdefault(type_name, list(labels))

    if not wanted:
        return

    # ALTER TYPE ... ADD VALUE cannot share a transaction with a statement that
    # uses the new member, so run each on its own autocommitting connection.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for type_name, members in wanted.items():
            rows = connection.execute(
                text(
                    "SELECT e.enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = :name"
                ),
                {"name": type_name},
            ).fetchall()
            if not rows:
                continue  # the type does not exist yet; create_all will make it
            present = {row[0] for row in rows}
            for member in members:
                if member in present:
                    continue
                connection.execute(
                    text(f'ALTER TYPE "{type_name}" ADD VALUE IF NOT EXISTS :value').bindparams(
                        value=member
                    )
                )
                logger.info("Added missing enum value %s.%s", type_name, member)


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
            # The bootstrap password comes from .env, so it is written down
            # somewhere and often shared. Make setting a real one the first
            # thing that happens.
            must_change_password=True,
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
    ensure_indexes()
    ensure_enum_values()
    create_first_admin()
