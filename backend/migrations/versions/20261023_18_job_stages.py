"""A job says which step it is on, not only how far along it is.

An import is several things in a row - download, read the files, re-apply
the recorded commands, rebuild the merges, run the project scripts, refresh
the indicators - and a progress number gave no way of telling which one was
running, or that one of them had passed over a merge without a word. Each job
now keeps its steps, written as they start and finish.

Nullable, so every job already in the table reads as having none.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_18"
down_revision = "20261018_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("jobs")}
    if "stages" not in columns:
        op.add_column("jobs", sa.Column("stages", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("jobs")}
    if "stages" in columns:
        op.drop_column("jobs", "stages")
