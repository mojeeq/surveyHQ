"""How somebody likes the interface, kept against the account.

The shell's preferences lived in the browser, so signing in from a different
computer meant setting them again, and clearing site data lost them. This adds
a small JSON column to carry the ones that belong to the person rather than to
the machine they happen to be sitting at.

A server default of {} rather than NULL, because every read treats it as a
mapping and a row that predates this column would otherwise need checking at
every call site.
"""

import sqlalchemy as sa

from app.db.migration_ops import add_column, drop_column

revision = "20261008_10"
down_revision = "20261008_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Through the helper, not op.add_column: an installation adopted from
    # before Alembic can arrive with this column already created by the
    # models, and ADD COLUMN on a name that exists stops the whole upgrade.
    add_column(
        "users",
        sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    drop_column("users", "preferences")
