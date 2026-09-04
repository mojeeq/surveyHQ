"""Indexes on columns that reached an existing database through ALTER TABLE.

create_all builds a table complete, indexes and all, and then never touches it
again. ensure_columns adds a column the models grew later - and adds only the
column. So every index declared on one of those is missing on exactly the
deployments that have been running longest, and the unique ones are missing as
constraints too: dashboards.public_hostname is declared unique, and without the
index two requests can each find a name free and then both take it.
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db.init_db import create_tables, ensure_indexes
from app.db.session import engine


def _index_names(table: str) -> set[str]:
    inspector = inspect(engine)
    return {index["name"] for index in inspector.get_indexes(table)} | {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table)
    }


def test_an_index_missing_from_an_existing_table_is_created():
    create_tables()
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
    create_tables()
    name = "ix_dashboards_public_hostname"
    with engine.begin() as connection:
        connection.execute(text(f"DROP INDEX {name}"))

    ensure_indexes()
    assert name in _index_names("dashboards")

    index = next(
        i for i in inspect(engine).get_indexes("dashboards") if i["name"] == name
    )
    assert index["unique"]


def test_running_it_twice_changes_nothing():
    """Start-up calls it on every boot, so it has to be a no-op when complete."""
    create_tables()
    ensure_indexes()
    before = _index_names("dashboards")
    ensure_indexes()
    assert _index_names("dashboards") == before


def test_every_declared_index_exists_after_a_normal_start():
    """Nothing the models declare should be missing on a database built here."""
    from app.db.base import Base

    create_tables()
    ensure_indexes()
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
