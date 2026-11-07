"""Add external survey and document connection link types."""

import sqlalchemy as sa
from alembic import op

revision = "20261107_25"
down_revision = "20261107_24"
branch_labels = None
depends_on = None

KINDS = ("odk_central", "surveycto", "cspro_csweb", "google_sheets", "kobotoolbox", "sharepoint")


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "connections", "base_url", existing_type=sa.String(500), type_=sa.String(2048)
        )
        # Separate transaction: PostgreSQL cannot use new enum values until committed.
        with op.get_context().autocommit_block():
            for kind in KINDS:
                op.execute(f"ALTER TYPE source_kind ADD VALUE IF NOT EXISTS '{kind}'")
    # SQLite stores this enum as unconstrained text.


def downgrade() -> None:
    # Retain additive enum values and saved links; removing them loses user data.
    pass
