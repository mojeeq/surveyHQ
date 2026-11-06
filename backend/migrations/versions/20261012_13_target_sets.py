"""A survey's quotas, kept as a list of their own.

Per-group targets lived inside the indicator that read them: a JSON column of
{category: number}. That is right for four provinces typed in once and wrong
for a census, where the targets are two thousand enumeration areas prepared
before fieldwork by somebody who is not watching a dashboard, and read by
several indicators at once - households enumerated, questionnaires received,
interviews verified, all against the same area quotas. Inside an indicator the
list had to be retyped for each one and could only be looked at through that
indicator's tile.

So a target set is its own record now, and an indicator points at one. The
inline targets stay exactly where they are: every indicator that carries them
goes on working, and this adds somewhere else to keep them rather than taking
anything away.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_13"
down_revision = "20261010_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "target_sets" not in tables:
        op.create_table(
            "target_sets",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column(
                "dataset_id",
                sa.String(length=36),
                sa.ForeignKey("datasets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "variable",
                sa.String(length=300),
                nullable=False,
                server_default=sa.text("''"),
            ),
            sa.Column("targets", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_target_sets_dataset_id", "target_sets", ["dataset_id"])

    if "indicators" in tables:
        columns = {column["name"] for column in inspector.get_columns("indicators")}
        if "target_set_id" not in columns:
            # Nullable, with no default: every existing indicator keeps reading
            # the targets it already carries.
            op.add_column(
                "indicators",
                sa.Column("target_set_id", sa.String(length=36), nullable=True),
            )
            op.create_index(
                "ix_indicators_target_set_id", "indicators", ["target_set_id"]
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "indicators" in tables:
        columns = {column["name"] for column in inspector.get_columns("indicators")}
        if "target_set_id" in columns:
            op.drop_index("ix_indicators_target_set_id", table_name="indicators")
            op.drop_column("indicators", "target_set_id")

    if "target_sets" in tables:
        op.drop_index("ix_target_sets_dataset_id", table_name="target_sets")
        op.drop_table("target_sets")
