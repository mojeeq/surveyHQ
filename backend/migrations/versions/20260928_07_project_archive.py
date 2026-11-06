"""Archiving a project: the data goes, everything built on it stays.

Deleting was the only way to stop a project costing disk, and it took the
dashboards, indicators, quality rules and script with it - months of work, none
of it large, to reclaim space taken by the microdata.

Three additions carry the difference: a project status saying the data has been
removed and when, a dataset status saying the same about one file, and a mark on
a share link saying archiving closed it - so unarchiving reopens those and
leaves alone the ones somebody closed on purpose.

Existing rows are untouched. Nothing is archived by this; it only becomes
possible.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_07"
down_revision = "20260928_06"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    postgres = bind.dialect.name == "postgresql"

    # PostgreSQL 12 and later allow a label to be added inside a transaction so
    # long as nothing uses it in the same one, which nothing here does. On
    # SQLite an enum is text with a check constraint and there is no type to
    # alter.
    if postgres:
        for type_name, label in (
            ("project_status", "archived"),
            ("dataset_status", "archived"),
        ):
            op.execute(
                sa.text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'")
            )

    # Asked rather than assumed: a database built straight from the models by
    # create_all already has these, and is then stamped and brought forward
    # through every migration from the beginning.
    for table, column, definition in (
        (
            "projects",
            "archived_at",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        ),
        (
            "share_links",
            "closed_by_archive",
            sa.Column(
                "closed_by_archive",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        ),
    ):
        if table not in inspector.get_table_names():
            continue
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        op.add_column(table, definition)


def downgrade():
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "share_links" in tables:
        op.drop_column("share_links", "closed_by_archive")
    if "projects" in tables:
        op.drop_column("projects", "archived_at")
    # The enum labels are left in place. PostgreSQL cannot remove one, and a
    # row already using it would have nothing to become.
