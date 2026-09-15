"""Helpers for revisions after the baseline.

This platform can be installed over a database that predates Alembic, so a
migration cannot assume the schema it is about to change is exactly what the
revision before it left. `legacy_migration.py` does that for the baseline and
is frozen at it; this is the same idea for everything that comes after.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def add_column(table: str, column: sa.Column) -> None:
    """Add a column unless the table already has one by that name.

    An adopted installation can arrive with a column a later revision was
    written to add - it was created by the models rather than by a migration -
    and ALTER TABLE ADD COLUMN on an existing name is a hard error that stops
    the upgrade and leaves the database marked unmigrated. Skipping one that is
    already there is the whole difference between an installation that starts
    and one that does not.
    """
    if column.name not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}:
        op.add_column(table, column)


def drop_column(table: str, name: str) -> None:
    """Drop a column if it is there, so a downgrade can be run twice."""
    if name in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}:
        op.drop_column(table, name)
