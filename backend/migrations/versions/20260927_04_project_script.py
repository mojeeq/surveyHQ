"""A project's do-file, and what its last run touched.

The table name is the one the R workspace used and 20260920_03 dropped. It is
reused deliberately rather than avoided: the old table is gone by then, and a
project's script is what this has always been the name for. What it holds is
different - one Stata script per project instead of a library of R files - so
the columns are written out fresh rather than restored.

`reads` and `writes` are what the last run actually touched. They are what lets
a newer export of one dataset re-run the scripts standing on it, and only
those.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_04"
down_revision = "20260920_03"
branch_labels = None
depends_on = None


def upgrade():
    # An installation that downgraded past 20260920_03 and came back has the R
    # table here instead. Dropped first, because the two share nothing but a
    # name and there is nothing in the old one worth carrying over: the R
    # workspace has not existed since 20260920_03.
    if "project_scripts" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("project_scripts")

    op.create_table(
        "project_scripts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_by",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reads", sa.JSON(), nullable=True),
        sa.Column("writes", sa.JSON(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", name="uq_project_script"),
    )
    op.create_index(
        "ix_project_scripts_project_id", "project_scripts", ["project_id"]
    )


def downgrade():
    op.drop_index("ix_project_scripts_project_id", table_name="project_scripts")
    op.drop_table("project_scripts")
