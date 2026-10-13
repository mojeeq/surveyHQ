"""A connection can be a folder instead of a server.

Creating an API user on a Survey Solutions server is an administrator's
privilege, and the answer is sometimes no - which left a platform that could
do nothing with the export the same people download by hand every morning.

So a connection says what kind of source it is. Every connection that exists
is a server connection and goes on being one; a folder connection carries a
directory instead of a URL, and a record per file it has already read, kept by
the file's content so that tomorrow's export under the same name is seen as
new and today's re-saved copy is not.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_15"
down_revision = "20261013_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "connections" in tables:
        columns = {column["name"] for column in inspector.get_columns("connections")}
        if "source_kind" not in columns:
            # Enum as text on SQLite, as a real type on Postgres; SQLAlchemy's
            # Enum does the right thing either way, and every existing row is
            # a server connection.
            op.add_column(
                "connections",
                sa.Column(
                    "source_kind",
                    sa.Enum("survey_solutions", "folder", name="source_kind"),
                    nullable=False,
                    server_default=sa.text("'survey_solutions'"),
                ),
            )
        if "folder_path" not in columns:
            op.add_column(
                "connections",
                sa.Column(
                    "folder_path",
                    sa.String(length=500),
                    nullable=False,
                    server_default=sa.text("''"),
                ),
            )

    if "folder_imports" not in tables:
        op.create_table(
            "folder_imports",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "connection_id",
                sa.String(length=36),
                sa.ForeignKey("connections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "file_name",
                sa.String(length=500),
                nullable=False,
                server_default=sa.text("''"),
            ),
            sa.Column("digest", sa.String(length=64), nullable=False),
            sa.Column("size", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("run_id", sa.String(length=36), nullable=True),
        )
        op.create_index("ix_folder_imports_connection_id", "folder_imports", ["connection_id"])
        op.create_index("ix_folder_imports_digest", "folder_imports", ["digest"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "folder_imports" in tables:
        op.drop_index("ix_folder_imports_digest", table_name="folder_imports")
        op.drop_index("ix_folder_imports_connection_id", table_name="folder_imports")
        op.drop_table("folder_imports")

    if "connections" in tables:
        columns = {column["name"] for column in inspector.get_columns("connections")}
        if "folder_path" in columns:
            op.drop_column("connections", "folder_path")
        if "source_kind" in columns:
            op.drop_column("connections", "source_kind")
            sa.Enum(name="source_kind").drop(bind, checkfirst=True)
