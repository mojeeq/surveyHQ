"""An enum column added to an existing table has to create its type first.

This has caught us twice. On SQLite an enum is text with a check constraint,
so a migration that adds one works and every test passes. On PostgreSQL the
column's type is a real object that must exist before a column can be of it,
and alembic does not create it for an added column the way CREATE TABLE does.
The migration then dies on a live database with

    type "source_kind" does not exist

which is the worst place to find out: the tests were green, and the deployment
is half upgraded.

So this reads the migrations rather than running them, and asks of every enum
column added to an existing table that the type be created, with checkfirst so
the migration stays safe to run twice, before the column that uses it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def migrations() -> list[Path]:
    return sorted(VERSIONS.glob("*.py"))


def test_there_are_migrations_to_check():
    """A guard that silently checks nothing is worse than no guard."""
    assert len(migrations()) > 5


def is_enum(node: ast.AST) -> bool:
    """Whether this expression is `sa.Enum(...)`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Enum"
    )


def created_with_checkfirst(call: ast.Call) -> str | None:
    """The name whose type is created here, if this is `<name>.create(bind, checkfirst=True)`."""
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "create"):
        return None
    if not isinstance(call.func.value, ast.Name):
        return None
    checkfirst = any(
        keyword.arg == "checkfirst" and keyword.value is not None
        for keyword in call.keywords
    )
    return call.func.value.id if checkfirst else None


def column_type(call: ast.Call) -> ast.AST | None:
    """The type given to `sa.Column(...)` inside an `op.add_column(...)`."""
    for argument in call.args:
        if (
            isinstance(argument, ast.Call)
            and isinstance(argument.func, ast.Attribute)
            and argument.func.attr == "Column"
            and len(argument.args) > 1
        ):
            return argument.args[1]
    return None


def enum_columns_added(tree: ast.AST) -> list[tuple[int, ast.AST]]:
    """Every `op.add_column` of an enum column, as (line, the type expression)."""
    found = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_column"
        ):
            continue
        given = column_type(node)
        if given is None:
            continue
        found.append((node.lineno, given))
    return found


@pytest.mark.parametrize("path", migrations(), ids=lambda path: path.stem)
def test_an_added_enum_column_has_its_type_created_first(path: Path):
    tree = ast.parse(path.read_text())

    # Names bound to an `sa.Enum(...)`, and where each one's type is created.
    enums = {
        target.id: node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and is_enum(node.value)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    creations = {
        name: node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := created_with_checkfirst(node))
    }

    for line, given in enum_columns_added(tree):
        if is_enum(given):
            pytest.fail(
                f"{path.name}:{line} adds a column whose type is sa.Enum(...) written "
                "in place. On PostgreSQL that type does not exist yet and the "
                "migration fails. Build it first - `kind = sa.Enum(..., name=...)`, "
                "`kind.create(bind, checkfirst=True)` - and pass `kind` here."
            )
        if not (isinstance(given, ast.Name) and given.id in enums):
            continue
        created = creations.get(given.id)
        assert created is not None, (
            f"{path.name}:{line} adds a column of enum `{given.id}`, whose type is "
            "never created. PostgreSQL needs "
            f"`{given.id}.create(bind, checkfirst=True)` before the column."
        )
        assert created < line, (
            f"{path.name}: the type of enum `{given.id}` is created at line {created}, "
            f"after the column that uses it at line {line}."
        )
