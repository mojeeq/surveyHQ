"""A quality check that is a condition rather than a shape.

The eight checks so far each answer one fixed question: is this variable blank
too often, is it outside a range, is it repeated. Anything else - a respondent
under 18 recorded as married, an interview that ends before it starts - could
not be asked at all.

This adds `logic` to the check types, so a rule can carry a condition and count
the rows that meet it. Nothing else changes: the condition itself goes in the
rule's existing JSON config, which needs no column.

Postgres stores check_type as a native enum, so the value has to be added to
the type. ALTER TYPE ... ADD VALUE cannot run inside a transaction block, and
Alembic opens one, so this commits first. SQLite keeps the column as VARCHAR
and needs nothing.
"""

from alembic import op

revision = "20261008_09"
down_revision = "20261006_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # IF NOT EXISTS so a database that already took this value - restored from
    # a dump taken after the upgrade, say - does not fail the migration.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE check_type ADD VALUE IF NOT EXISTS 'logic'")


def downgrade() -> None:
    """Left alone on purpose.

    Removing a value from a Postgres enum means rebuilding the type and every
    column using it, and it would fail anyway while a single rule still holds
    the value. Downgrading past this is safe with the value present: nothing
    reads it unless a rule carries it.
    """
