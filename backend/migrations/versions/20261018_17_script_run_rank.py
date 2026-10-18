"""An order somebody chose, where the data does not choose one.

The Scripts page reads the running order off what each run opened and saved:
a script that writes what another reads has to go first, and that part is not
anybody's to rearrange. Within a step it is - the scripts there wait on
nothing from each other and the page says so - and until now their order on
the page was alphabetical, which is no order at all for somebody who knows
which one they do first on a Monday.

So a script carries a rank, used only to order it among the scripts it shares
a step with. Zero everywhere to begin with, which leaves the alphabetical
order exactly as it was until somebody moves something.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261018_17"
down_revision = "20261018_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_scripts")}
    if "run_rank" not in columns:
        op.add_column(
            "project_scripts",
            sa.Column(
                "run_rank",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_scripts")}
    if "run_rank" in columns:
        op.drop_column("project_scripts", "run_rank")
