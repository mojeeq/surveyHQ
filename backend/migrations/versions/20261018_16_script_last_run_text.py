"""What a run ran, so the editor is not blank afterwards.

Running a script and saving it are deliberately separate: a script is tried
before it is kept, so that a run which fails does not have to be undone by
hand. The cost was that a script run and never saved left nothing behind but
the fact that it ran. The editor opened empty, the overview said "Run without
being saved", and the commands that actually built the data were gone.

So a run keeps the text it ran, beside the text somebody saved rather than
instead of it. The saved script is still the script; this is what the editor
offers when there is no saved one, and what the overview counts so that a
card can say how long the thing that ran was.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261018_16"
down_revision = "20261013_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_scripts")}
    if "last_run_text" not in columns:
        op.add_column(
            "project_scripts",
            sa.Column(
                "last_run_text",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("project_scripts")}
    if "last_run_text" in columns:
        op.drop_column("project_scripts", "last_run_text")
