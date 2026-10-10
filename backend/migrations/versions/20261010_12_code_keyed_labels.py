"""Value labels keyed the way a code is written.

SPSS stores every number as a double, so its reader handed back label keys of
1.0 where Stata's were 1 - and a lookup asks for "1". Every value label an
imported .sav carried was therefore unreachable: a crosstab of a labelled
question printed 1.0, 2.0, 3.0, the labels sat in the dataset unused, and
nothing on the screen said they were there.

The readers are fixed. This is for what is already stored, so a dataset
imported before the fix shows its labels without being imported again. It
touches the labels on the variables and the ones written by hand, which are
kept on the dataset so they survive a replacement.

Only for columns that hold numbers, and only for keys that are whole numbers:
a text column whose values really are "1.0" is read by "1.0". A key already in
normal form wins over one that is not - "1" and "1.0" in the same set are one
code, and the one the data is read by is "1".
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20261010_12"
down_revision = "20261010_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()

    if "variables" not in tables:
        return

    rows = bind.execute(
        sa.text(
            "SELECT id, dataset_id, name, storage_type, value_labels FROM variables "
            "WHERE value_labels IS NOT NULL"
        )
    ).fetchall()
    # Which columns hold numbers, so the repair can leave the others alone.
    numeric: dict[tuple, bool] = {}
    for variable_id, dataset_id, name, storage_type, raw in rows:
        holds_numbers = _numeric(storage_type)
        numeric[(dataset_id, name)] = holds_numbers
        if not holds_numbers:
            continue
        labels = _loads(raw)
        fixed = _normalised(labels)
        if fixed != labels:
            bind.execute(
                sa.text("UPDATE variables SET value_labels = :v WHERE id = :i"),
                {"v": json.dumps(fixed), "i": variable_id},
            )

    if "datasets" in tables:
        rows = bind.execute(
            sa.text("SELECT id, meta FROM datasets WHERE meta IS NOT NULL")
        ).fetchall()
        for dataset_id, raw in rows:
            meta = _loads(raw)
            overrides = meta.get("variable_labels")
            if not isinstance(overrides, dict):
                continue
            changed = False
            for name, stored in list(overrides.items()):
                if not isinstance(stored, dict):
                    continue
                labels = stored.get("value_labels")
                if not isinstance(labels, dict):
                    continue
                if not numeric.get((dataset_id, name), False):
                    continue
                fixed = _normalised(labels)
                if fixed != labels:
                    overrides[name] = {**stored, "value_labels": fixed}
                    changed = True
            if changed:
                meta["variable_labels"] = overrides
                bind.execute(
                    sa.text("UPDATE datasets SET meta = :m WHERE id = :i"),
                    {"m": json.dumps(meta), "i": dataset_id},
                )


def downgrade() -> None:
    # Nothing to undo: "1" is what every other part of the platform writes, and
    # putting the decimal point back would hide the labels again.
    pass


def _normalised(labels: dict) -> dict:
    """The same labels, keyed as the data is read.

    Written out here rather than imported from the services, so the migration
    goes on meaning what it meant however that code is reorganised later.
    """
    if not isinstance(labels, dict):
        return labels
    fixed: dict[str, str] = {}
    # Already in normal form first, so a set holding both spellings keeps the
    # one the data is read by.
    for key, value in labels.items():
        if _code(key) == str(key):
            fixed[str(key)] = value
    for key, value in labels.items():
        fixed.setdefault(_code(key), value)
    return fixed


# Both vocabularies appear in this column: pandas writes "float64" and the
# Parquet profiler writes "DOUBLE".
NUMERIC_TOKENS = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT")


def _numeric(storage_type) -> bool:
    return any(token in str(storage_type).upper() for token in NUMERIC_TOKENS)


def _code(key) -> str:
    text = str(key)
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    return str(int(number)) if number.is_integer() else text


def _loads(raw) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}
