"""Dashboards published to a web server elsewhere.

Two tables: the destinations - a GitHub Pages repository, a server reached
over SFTP, an FTP host - and the publications, one dashboard at one address on
one of them. Nothing is published by this; it only becomes possible.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261029_22"
down_revision = "20261027_21"
branch_labels = None
depends_on = None


def _user():
    return sa.ForeignKey("users.id", ondelete="SET NULL")


def _stamps():
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "publish_targets" not in tables:
        op.create_table(
            "publish_targets",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("settings", sa.JSON(), nullable=True),
            sa.Column(
                "secret_encrypted", sa.Text(), nullable=False, server_default=sa.text("''")
            ),
            sa.Column("created_by", sa.String(length=36), _user(), nullable=True),
            *_stamps(),
        )
        op.create_index("ix_publish_targets_id", "publish_targets", ["id"])

    if "publications" not in tables:
        op.create_table(
            "publications",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "dashboard_id",
                sa.String(length=36),
                sa.ForeignKey("dashboards.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "target_id",
                sa.String(length=36),
                sa.ForeignKey("publish_targets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("path", sa.String(length=200), nullable=False, server_default=sa.text("''")),
            sa.Column(
                "view_id", sa.String(length=36), nullable=False, server_default=sa.text("''")
            ),
            sa.Column(
                "auto_republish", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'published'"),
            ),
            sa.Column("url", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("notes", sa.JSON(), nullable=True),
            sa.Column("published_by", sa.String(length=36), _user(), nullable=True),
            sa.Column("created_by", sa.String(length=36), _user(), nullable=True),
            *_stamps(),
            sa.UniqueConstraint("target_id", "path", name="uq_publication_address"),
        )
        op.create_index("ix_publications_id", "publications", ["id"])
        op.create_index("ix_publications_dashboard_id", "publications", ["dashboard_id"])
        op.create_index("ix_publications_target_id", "publications", ["target_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "publications" in tables:
        op.drop_table("publications")
    if "publish_targets" in tables:
        op.drop_table("publish_targets")
