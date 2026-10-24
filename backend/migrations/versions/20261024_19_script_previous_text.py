"""A run that goes through keeps its script, and the one it replaced is kept.

Running and saving were separate, so a script could be tried without being
kept, and that was how scripts went missing from the re-run on a newer export:
run, seen to work, never saved. A clean run now keeps what ran. The saved
script it replaces goes here, one deep, so trying something over a good script
is a click from undone.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261024_19"
down_revision = "20261023_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_scripts")}
    if "previous_text" not in columns:
        op.add_column(
            "project_scripts",
            sa.Column("previous_text", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_scripts")}
    if "previous_text" in columns:
        op.drop_column("project_scripts", "previous_text")
