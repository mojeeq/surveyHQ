"""One-time adoption helpers for revision 20260914_01. Keep these frozen."""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM


def adopt_table(name, *elements, **kwargs):
    bind = op.get_bind()
    for column in elements:
        if not isinstance(column, sa.Column) or not isinstance(column.type, sa.Enum):
            continue
        if bind.dialect.name == "postgresql":
            kind = ENUM(*column.type.enums, name=column.type.name, create_type=False)
            kind.create(bind, checkfirst=True)
            with op.get_context().autocommit_block():
                for label in kind.enums:
                    # Labels and type names are frozen migration constants.
                    op.execute(
                        sa.text(
                            f'ALTER TYPE "{kind.name}" ADD VALUE IF NOT EXISTS :value'
                        ).bindparams(value=label)
                    )
            column.type = kind
    inspector = sa.inspect(bind)
    if name not in inspector.get_table_names():
        op.create_table(name, *elements, **kwargs)
        return
    existing = {c["name"] for c in inspector.get_columns(name)}
    for column in elements:
        if isinstance(column, sa.Column) and column.name not in existing:
            # Fail on an unsafe NOT NULL addition; never mark an incomplete
            # schema as migrated. The operator must repair the legacy data.
            op.add_column(name, column)
    # The legacy system did not evolve table-level unique constraints.
    present = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(name)}
    for constraint in elements:
        if isinstance(constraint, sa.UniqueConstraint):
            columns = tuple(c.name for c in constraint.columns) or tuple(
                constraint._pending_colargs
            )
            if columns and columns not in present:
                with op.batch_alter_table(name) as batch:
                    batch.create_unique_constraint(
                        constraint.name or f"uq_{name}_{'_'.join(columns)}", list(columns)
                    )


def adopt_index(name, table, columns, **kwargs):
    bind = op.get_bind()
    # Legacy accounts need handles before the unique index can be built.
    if table == "users" and columns == ["username"]:
        rows = bind.execute(sa.text("SELECT id, email, username FROM users")).mappings().all()
        used = {r["username"] for r in rows if r["username"]}
        for row in rows:
            if row["username"]:
                continue
            base = re.sub(r"[^a-z0-9._-]", "", row["email"].split("@")[0].lower())[:50] or "user"
            candidate, suffix = base, 1
            while candidate in used:
                suffix += 1
                candidate = f"{base}{suffix}"
            bind.execute(
                sa.text("UPDATE users SET username=:name WHERE id=:id"),
                {"name": candidate, "id": row["id"]},
            )
            used.add(candidate)
    inspector = sa.inspect(bind)
    names = {i["name"] for i in inspector.get_indexes(table)} | {
        c["name"] for c in inspector.get_unique_constraints(table)
    }
    if name not in names:
        op.create_index(name, table, columns, **kwargs)
