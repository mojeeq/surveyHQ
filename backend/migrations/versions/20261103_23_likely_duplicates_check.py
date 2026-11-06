"""A quality check for records that are probably one person entered twice.

The exact duplicate check asks whether a key repeats. This one compares records
field by field - names by spelling, ages and dates within a tolerance - and
flags pairs alike enough to be the same person or household. Its settings live
in the rule's existing JSON config, so the only change is the new value of the
check type.

Postgres stores check_type as a native enum, so the value has to be added to
the type, outside a transaction block as ALTER TYPE ... ADD VALUE requires.
SQLite keeps the column as VARCHAR and needs nothing.
"""

from alembic import op

revision = "20261103_23"
down_revision = "20261029_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE check_type ADD VALUE IF NOT EXISTS 'likely_duplicates'")


def downgrade() -> None:
    """Left alone, as for the logic check: a value cannot be taken out of a
    Postgres enum without rebuilding it, and nothing reads this one unless a
    rule carries it."""
