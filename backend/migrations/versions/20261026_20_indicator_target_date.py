"""The day an indicator's target is meant to be met by.

A target says how many; fieldwork also has a last day. With both, a tile can
say how many a day it now takes to finish on time, which is the number a field
manager plans the week around. Optional, and empty for every indicator that
has none.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261026_20"
down_revision = "20261024_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("indicators")}
    if "target_date" not in columns:
        op.add_column("indicators", sa.Column("target_date", sa.Date(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("indicators")}
    if "target_date" in columns:
        op.drop_column("indicators", "target_date")
