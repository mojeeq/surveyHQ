"""How a relationship's two keys are lined up before they are compared.

A merge between a text key and a numeric one is refused, because comparing
them means deciding which side to convert and no rule can make that decision
safely: converting "H0041" to a number fails, and converting 41 to text gives
"41", which is not "H0041" either.

Where the two really are the same households written two ways - a survey run
twice, one export quoting its ids and the next not - the person who knows the
survey can now say so on the relationship, and the merge converts both sides
the way they asked.

Existing relationships get `exact`, which is what they have always done.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_06"
down_revision = "20260927_05"
branch_labels = None
depends_on = None

MATCHES = ("exact", "text", "number")
TYPE_NAME = "relationship_key_match"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dataset_relationships" not in inspector.get_table_names():
        return

    kind = sa.Enum(*MATCHES, name=TYPE_NAME)
    # PostgreSQL needs the type to exist before a column can be of it, and
    # alembic does not create it for an added column the way CREATE TABLE does.
    # On SQLite an enum is text with a check and this does nothing.
    kind.create(bind, checkfirst=True)

    # A database built straight from the models by create_all already has the
    # column, and is then stamped and brought forward through every migration
    # from the beginning. Adding it again is a duplicate-column error, so this
    # asks rather than assumes - which also makes the migration safe to run
    # twice.
    if "key_match" in {column["name"] for column in inspector.get_columns("dataset_relationships")}:
        return

    op.add_column(
        "dataset_relationships",
        sa.Column(
            "key_match",
            kind,
            nullable=False,
            server_default="exact",
        ),
    )


def downgrade():
    bind = op.get_bind()
    if "dataset_relationships" in sa.inspect(bind).get_table_names():
        op.drop_column("dataset_relationships", "key_match")
    sa.Enum(*MATCHES, name=TYPE_NAME).drop(bind, checkfirst=True)
