"""Indexes on columns that reached an existing database through ALTER TABLE.

create_all builds a table complete, indexes and all, and then never touches it
again. ensure_columns adds a column the models grew later - and adds only the
column, because PostgreSQL drops a column's indexes along with the column and
nothing puts them back. So every index declared on one of those is missing on
exactly the deployments that have been running longest, and the unique ones are
missing as constraints too: dashboards.public_hostname is declared unique, and
without the index two requests can each find a name free and then both take it.

These tests damage the schema on purpose, so each one owns its starting point
rather than assuming a complete database. It cannot assume one: the upgrade
tests in test_schema_evolution.py drop and re-add dashboards.project_id, which
on PostgreSQL leaves the database in precisely the state this module exists to
repair.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.init_db import create_tables, ensure_columns, ensure_indexes
from app.db.session import engine


def _index_names(table: str) -> set[str]:
    inspector = inspect(engine)
    return {index["name"] for index in inspector.get_indexes(table)} | {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table)
    }


@pytest.fixture(autouse=True)
def complete_schema():
    """Start every test from a database with every declared index present."""
    create_tables()
    ensure_indexes()
    yield
    ensure_indexes()


def test_an_index_missing_from_an_existing_table_is_created():
    name = "ix_dashboards_project_id"
    assert name in _index_names("dashboards")

    with engine.begin() as connection:
        connection.execute(text(f"DROP INDEX {name}"))
    assert name not in _index_names("dashboards")

    ensure_indexes()
    assert name in _index_names("dashboards")


def test_a_unique_index_is_restored_as_a_constraint():
    """public_hostname is what a dashboard's own address is looked up by.

    Losing the index costs a scan per request; losing the uniqueness lets two
    dashboards answer on one name.
    """
    name = "ix_dashboards_public_hostname"
    with engine.begin() as connection:
        connection.execute(text(f"DROP INDEX {name}"))

    ensure_indexes()
    assert name in _index_names("dashboards")

    index = next(
        i for i in inspect(engine).get_indexes("dashboards") if i["name"] == name
    )
    assert index["unique"]


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="SQLite will not drop a column an index still refers to.",
)
def test_a_column_re_added_by_an_upgrade_gets_its_index_back():
    """The whole point, in the shape it actually happens.

    A column the models grew later reaches a live database through ALTER TABLE
    ADD COLUMN. PostgreSQL had dropped its index along with the old column, and
    ensure_columns adds back only the column - so the index stayed missing
    until something asked for it. This is that something.
    """
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE dashboards DROP COLUMN project_id"))

    ensure_columns()
    columns = {c["name"] for c in inspect(engine).get_columns("dashboards")}
    assert "project_id" in columns
    # The state a deployment was actually left in: column back, index gone.
    assert "ix_dashboards_project_id" not in _index_names("dashboards")

    ensure_indexes()
    assert "ix_dashboards_project_id" in _index_names("dashboards")


def test_running_it_twice_changes_nothing():
    """Start-up calls it on every boot, so it has to be a no-op when complete."""
    before = _index_names("dashboards")
    ensure_indexes()
    assert _index_names("dashboards") == before


def test_every_declared_index_exists_after_a_normal_start():
    """Nothing the models declare should be missing once start-up has run."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = [
        f"{table.name}.{index.name}"
        for table in Base.metadata.sorted_tables
        if table.name in tables
        for index in table.indexes
        if index.name not in _index_names(table.name)
    ]
    assert missing == []
