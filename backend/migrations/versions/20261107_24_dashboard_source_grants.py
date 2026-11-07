"""Track validated dashboard data-source access."""

import sqlalchemy as sa
from alembic import op

revision = "20261107_24"
down_revision = "20261103_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("dashboards")}
    if "source_grants" not in columns:
        op.add_column("dashboards", sa.Column(
            "source_grants", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ))


def downgrade() -> None:
    op.drop_column("dashboards", "source_grants")
