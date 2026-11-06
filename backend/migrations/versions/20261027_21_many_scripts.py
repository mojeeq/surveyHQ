"""A project can have several scripts, each with a name.

It had one, held to it by a unique constraint on the project. The constraint
goes, and every script gets a name - "Main script" for the one a project
already has.

The rows that were never scripts go too. Opening a project's script tab used
to make an empty row, so most projects carry one with no text, no run and
nothing recorded. The page hid them while there could only be one; with
several, every row is a script in the list, and those would be a "Main
script" nobody wrote in every project that was ever looked at.
"""

import sqlalchemy as sa
from alembic import op

from app.db.migration_ops import add_column, drop_column

revision = "20261027_21"
down_revision = "20261026_20"
branch_labels = None
depends_on = None


def _one_per_project(bind) -> list[str]:
    """The unique constraints holding a project to one script, by name."""
    return [
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints("project_scripts")
        if constraint.get("name") and constraint.get("column_names") == ["project_id"]
    ]


def upgrade() -> None:
    bind = op.get_bind()
    add_column(
        "project_scripts",
        sa.Column("name", sa.String(length=120), nullable=False, server_default="Main script"),
    )
    held = _one_per_project(bind)
    if held:
        # A table rebuild on SQLite, which cannot drop a constraint in place.
        with op.batch_alter_table("project_scripts") as batch:
            for name in held:
                batch.drop_constraint(name, type_="unique")
    op.execute(
        "DELETE FROM project_scripts "
        "WHERE TRIM(COALESCE(text, '')) = '' "
        "AND last_run_at IS NULL "
        "AND TRIM(COALESCE(last_run_text, '')) = ''"
    )


def downgrade() -> None:
    bind = op.get_bind()
    crowded = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT project_id FROM project_scripts "
            "GROUP BY project_id HAVING COUNT(*) > 1) AS crowded"
        )
    ).scalar()
    if crowded:
        # Putting the constraint back would fail on these, and picking which
        # script to throw away is not a migration's decision.
        raise RuntimeError(
            f"{crowded} project(s) have more than one script. Delete the extra "
            "scripts before downgrading past 20261027_21."
        )
    if not _one_per_project(bind):
        with op.batch_alter_table("project_scripts") as batch:
            batch.create_unique_constraint("uq_project_script", ["project_id"])
    drop_column("project_scripts", "name")
