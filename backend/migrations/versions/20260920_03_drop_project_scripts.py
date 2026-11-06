"""Drop the R script workspace, now that the command box is Stata again.

The table held a project's saved R scripts. Nothing reads it any more, and a
table nothing reads is a place for a future reader to be misled about what the
platform does.

Dropped rather than emptied, and it takes the scripts with it. R was off unless
an installation set R_SCRIPTS_ENABLED, so most carry nothing here; one that ran
scripts should copy them out before upgrading, because the downgrade rebuilds
the table but cannot bring their contents back.

The Stata commands are untouched by this. They were never in a table of their
own: they live in datasets.meta, which is why they survived the swap in both
directions without a migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_03"
down_revision = "20260915_02"
branch_labels = None
depends_on = None


def upgrade():
    # Checked first: an installation that never ran the R revision, or that was
    # adopted from before Alembic, has nothing to drop and should not fail here.
    if "project_scripts" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("project_scripts")


def downgrade():
    if "project_scripts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "project_scripts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("code", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "run_on_import", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_output", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_by",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
