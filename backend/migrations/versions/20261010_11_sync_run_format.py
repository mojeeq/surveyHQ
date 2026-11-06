"""Which format an import asked the Survey Solutions server for.

The format could only be set on the connection, so every import used whatever
it was set to last. It can now be chosen per import - a round whose Stata file
reads badly is re-pulled as tabular - and the run has to record which, or the
history cannot say what any of it came in as.

Empty rather than NULL for the runs that predate this: every read treats it as
a string, and "nothing recorded" is what it honestly says.
"""

import sqlalchemy as sa

from app.db.migration_ops import add_column, drop_column

revision = "20261010_11"
down_revision = "20261008_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Through the helper, not op.add_column: an installation adopted from
    # before Alembic can arrive with this column already created by the
    # models, and ADD COLUMN on a name that exists stops the whole upgrade.
    add_column(
        "sync_runs",
        sa.Column("export_format", sa.String(20), nullable=False, server_default=sa.text("''")),
    )


def downgrade() -> None:
    drop_column("sync_runs", "export_format")
