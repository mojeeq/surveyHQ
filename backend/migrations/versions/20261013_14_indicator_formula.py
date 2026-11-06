"""An indicator can be a sum of its parts.

An indicator was one aggregate over one filter, with a switch saying "and
divide that by the row count". That covers "how many" and "what share of
everything" and stops there, so the questions a survey office actually puts on
a board - refusals per completed interview, the share among those who answered
one question rather than among every row, the gap between visits and
interviews - had to be kept on paper and worked out by hand.

This adds one column: the parts of such a sum and the expression combining
them. Empty for every indicator that exists, which goes on being read exactly
as before - the formula is another way to define one, not a replacement for
the way that is there.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_14"
down_revision = "20261012_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "indicators" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("indicators")}
    if "formula" not in columns:
        op.add_column(
            "indicators",
            sa.Column(
                "formula",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "indicators" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("indicators")}
    if "formula" in columns:
        op.drop_column("indicators", "formula")
