"""Named groups of widgets on a dashboard page.

Both columns carry a server default so they can be added to tables that
already hold rows: without one the NOT NULL has nothing to fill in.

They are added through the helpers rather than op.add_column directly, because
an installation adopted from before Alembic can already have a column a later
revision was written to add.
"""

import sqlalchemy as sa

from app.db.migration_ops import add_column, drop_column

revision = "20260915_02"
down_revision = "20260914_01"
branch_labels = None
depends_on = None


def upgrade():
    add_column(
        "dashboards",
        sa.Column("groups", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    add_column(
        "widgets",
        sa.Column(
            "group_id",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )


def downgrade():
    drop_column("widgets", "group_id")
    drop_column("dashboards", "groups")
