"""Carry the per-dataset commands into their project's script.

The command box moved from the dataset to the project, and the commands people
already wrote have to move with it or they become invisible: still re-applied
after every import, with nowhere in the interface to read or clear them.

Each dataset's history becomes a section of its project's script, in the form
the project engine reads:

    * Carried over from the command box on <dataset>
    use <dataset>
    <the commands, in the order they were recorded>
    save, replace

which does exactly what the replay did - the same commands against the same
dataset, written back over it - and now says so somewhere a person can see.

A dataset with no project has nowhere to move to. Its commands stay where they
are and keep being replayed, which is the behaviour it had; those installations
see no change at all.

Names are quoted, because a dataset called "Round 2" is two words to a parser
that splits on spaces.

The downgrade cannot take a section back out of a script somebody has since
edited, so it does not try. It leaves the scripts alone; the datasets' own
histories were never removed for datasets without a project, and for the rest
the script is now the record.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20260927_05"
down_revision = "20260927_04"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "project_scripts" not in tables or "datasets" not in tables:
        return

    rows = bind.execute(
        sa.text(
            "SELECT id, name, project_id, meta FROM datasets "
            "WHERE project_id IS NOT NULL"
        )
    ).fetchall()

    sections: dict[str, list[str]] = {}
    carried: list[str] = []
    for dataset_id, name, project_id, meta in rows:
        commands = _commands(meta)
        if not commands:
            continue
        lines = [f"* Carried over from the command box on {name}", f'use "{name}"']
        lines.extend(commands)
        lines.append("save, replace")
        sections.setdefault(project_id, []).append("\n".join(lines))
        carried.append(dataset_id)

    for project_id, blocks in sections.items():
        existing = bind.execute(
            sa.text("SELECT id, text FROM project_scripts WHERE project_id = :p"),
            {"p": project_id},
        ).fetchone()
        addition = "\n\n".join(blocks)
        if existing is None:
            bind.execute(
                sa.text(
                    "INSERT INTO project_scripts (id, project_id, text, reads, writes,"
                    " last_error) VALUES (:i, :p, :t, :r, :w, '')"
                ),
                {
                    "i": _new_id(),
                    "p": project_id,
                    "t": addition,
                    "r": json.dumps([]),
                    "w": json.dumps([]),
                },
            )
        else:
            joined = f"{existing[1]}\n\n{addition}" if existing[1].strip() else addition
            bind.execute(
                sa.text("UPDATE project_scripts SET text = :t WHERE id = :i"),
                {"t": joined, "i": existing[0]},
            )

    # Cleared only where it was carried, so the replay does not run them a
    # second time on the next import - the script does that now.
    for dataset_id in carried:
        meta = bind.execute(
            sa.text("SELECT meta FROM datasets WHERE id = :i"), {"i": dataset_id}
        ).scalar()
        holder = _loads(meta)
        holder.pop("commands", None)
        bind.execute(
            sa.text("UPDATE datasets SET meta = :m WHERE id = :i"),
            {"m": json.dumps(holder), "i": dataset_id},
        )


def downgrade():
    # Nothing to undo. A section cannot be taken back out of a script somebody
    # has since edited, and putting the commands back on the datasets would
    # have them run twice.
    pass


def _commands(meta) -> list[str]:
    holder = _loads(meta)
    found = holder.get("commands") or []
    return [str(one) for one in found if str(one).strip()]


def _loads(meta) -> dict:
    if isinstance(meta, dict):
        return dict(meta)
    if not meta:
        return {}
    try:
        loaded = json.loads(meta)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())
