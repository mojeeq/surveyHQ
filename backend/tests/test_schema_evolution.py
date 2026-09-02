"""Upgrading an existing database in place.

create_all creates missing tables and never touches what already exists, so a
new column or a new enum member reaches a running deployment only as a failure
at the first request that uses it. Both faults happened here: a missing
variables.missing_tags column, and

    invalid input value for enum chart_type: "crosstab"

Neither is reproducible on SQLite - it has no native enum type and stores these
as text - and neither appears in a database built from scratch, because that one
is created complete. They exist only on an upgrade, which is what these tests
simulate.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.db.init_db import create_tables, ensure_columns, ensure_enum_values
from app.db.session import engine

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="These faults only exist on PostgreSQL; SQLite stores both as text.",
)


@pytest.fixture(scope="module", autouse=True)
def schema():
    """Build the schema here rather than relying on another test having built it.

    These tests damage the schema on purpose, so they must own it: an empty
    database would otherwise make them fail for the wrong reason, and a database
    left over from an earlier run would make them pass for one.
    """
    create_tables()
    yield


def test_a_column_added_to_a_model_is_added_to_an_existing_table():
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE variables DROP COLUMN IF EXISTS missing_tags'))

    assert "missing_tags" not in {
        c["name"] for c in inspect(engine).get_columns("variables")
    }

    ensure_columns()

    assert "missing_tags" in {
        c["name"] for c in inspect(engine).get_columns("variables")
    }


def test_an_enum_member_added_to_a_model_is_added_to_an_existing_type():
    """The exact failure: saving a cross-tab chart returned 500 on a live server."""

    def labels() -> set[str]:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t "
                    "ON t.oid = e.enumtypid WHERE t.typname = 'chart_type'"
                )
            ).fetchall()
        return {row[0] for row in rows}

    assert "crosstab" in labels()

    # A type cannot have a value removed, so prove it the other way round: a
    # brand new member on a type that already exists gets added.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("DROP TYPE IF EXISTS upgrade_probe"))
        connection.execute(text("CREATE TYPE upgrade_probe AS ENUM ('one')"))

    from sqlalchemy import Column, Enum, MetaData, String, Table

    probe_metadata = MetaData()
    Table(
        "upgrade_probe_table",
        probe_metadata,
        Column("id", String(8), primary_key=True),
        Column("value", Enum("one", "two", name="upgrade_probe")),
    )

    from app.db import init_db

    original = init_db.Base.metadata
    try:
        init_db.Base.metadata = probe_metadata
        ensure_enum_values()
    finally:
        init_db.Base.metadata = original

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t "
                "ON t.oid = e.enumtypid WHERE t.typname = 'upgrade_probe'"
            )
        ).fetchall()
    assert {row[0] for row in rows} == {"one", "two"}

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("DROP TYPE IF EXISTS upgrade_probe"))


def test_the_labels_used_are_the_ones_sqlalchemy_sends():
    """Deriving labels from the Python enum gets ExportFormat wrong.

    Its members are named "stata" but valued "STATA"; the database holds the
    name. Since this only ever adds, a wrong list adds junk labels that
    PostgreSQL cannot remove.
    """
    from app.models.connection import Connection, ExportFormat

    declared = Connection.__table__.c.export_format.type.enums
    assert declared == [member.name for member in ExportFormat]
    assert declared != [member.value for member in ExportFormat]


def test_the_project_columns_reach_an_existing_database():
    """Projects arrived after deployments existed, so they arrive by ALTER TABLE.

    Getting this wrong is not a crash but something worse: datasets and
    dashboards that a running server can no longer read at all.
    """
    with engine.begin() as connection:
        for table in ("datasets", "dashboards"):
            connection.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS project_id"))
        connection.execute(
            text("ALTER TABLE users DROP COLUMN IF EXISTS restricted_to_projects")
        )

    ensure_columns()

    inspector = inspect(engine)
    for table in ("datasets", "dashboards"):
        assert "project_id" in {c["name"] for c in inspector.get_columns(table)}
    users = {c["name"]: c for c in inspector.get_columns("users")}
    assert "restricted_to_projects" in users
    # NOT NULL with no default would fail outright on a table that has rows.
    assert users["restricted_to_projects"]["nullable"] is False


def test_everything_that_existed_before_projects_stays_in_the_shared_area():
    """The upgrade must not hide data behind a project nobody is a member of."""
    with engine.connect() as connection:
        stranded = connection.execute(
            text(
                "SELECT count(*) FROM datasets WHERE project_id IS NOT NULL "
                "AND project_id NOT IN (SELECT id FROM projects)"
            )
        ).scalar()
    assert stranded == 0
