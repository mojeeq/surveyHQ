"""Keeping a board as it stood, on a schedule.

A saved view remembers a filter selection and nothing else, so a board opened
through one always shows today's numbers however the view is named. Naming
views after dates - which is what people reach for - makes it look as though
the board remembers, and it does not.

This adds the half that does: a schedule on the dashboard saying which days and
times to capture it, and a table of captures. Each capture is the same
self-contained file the export button produces, written to disk, so opening the
one from the 7th shows the 7th.

Nothing is captured by this; it only becomes possible. Every existing dashboard
arrives with the schedule off.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_08"
down_revision = "20260928_07"
branch_labels = None
depends_on = None


SCHEDULE = (
    # Server defaults throughout: these land on a table that already has rows,
    # and a NOT NULL column with nothing to put in it fails the upgrade.
    ("snapshot_enabled", sa.Boolean(), sa.text("false")),
    ("snapshot_times", sa.JSON(), sa.text("'[]'")),
    ("snapshot_days", sa.JSON(), sa.text("'[]'")),
    ("snapshot_timezone", sa.String(length=64), sa.text("'UTC'")),
    ("snapshot_keep", sa.Integer(), sa.text("12")),
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("dashboards")}

    for name, type_, default in SCHEDULE:
        if name in existing:
            continue
        op.add_column(
            "dashboards",
            sa.Column(name, type_, nullable=False, server_default=default),
        )
    if "last_snapshot_at" not in existing:
        op.add_column(
            "dashboards",
            sa.Column("last_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "dashboard_snapshots" in inspector.get_table_names():
        return

    op.create_table(
        "dashboard_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "dashboard_id",
            sa.String(length=36),
            sa.ForeignKey("dashboards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "is_automatic", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_by",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_dashboard_snapshots_dashboard_id", "dashboard_snapshots", ["dashboard_id"]
    )
    # Listed newest first, always, and pruned oldest first.
    op.create_index("ix_dashboard_snapshots_taken_at", "dashboard_snapshots", ["taken_at"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dashboard_snapshots" in inspector.get_table_names():
        op.drop_index("ix_dashboard_snapshots_taken_at", table_name="dashboard_snapshots")
        op.drop_index(
            "ix_dashboard_snapshots_dashboard_id", table_name="dashboard_snapshots"
        )
        op.drop_table("dashboard_snapshots")
    existing = {column["name"] for column in inspector.get_columns("dashboards")}
    for name in ("last_snapshot_at", *[row[0] for row in SCHEDULE]):
        if name in existing:
            op.drop_column("dashboards", name)
