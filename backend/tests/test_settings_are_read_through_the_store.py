"""A tunable setting read straight off the configuration is a setting that lies.

Seventeen settings can be changed from inside the platform, and every one of
them works by being read through `preferences.value` rather than off the
settings object. A new read site that goes to the configuration directly
would keep answering with what .env said, so the page would move a number
that nothing acted on - which is worse than not offering it.

This is the guard for that: it reads the source rather than the behaviour,
because the behaviour would only show up where somebody had already written
a test for that particular setting.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from app.services import preferences

#: Where a tunable setting may still be read off the configuration.
#:
#: config.py declares them; preferences.py is the store itself and falls back
#: to them, which is the point of it.
ALLOWED = {
    Path("app/core/config.py"),
    Path("app/services/preferences.py"),
}

TUNABLE = set(preferences.BY_NAME)


def _reads(path: Path) -> set[str]:
    """Which tunable settings this file reads as `settings.<name>`."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in TUNABLE:
            continue
        held = node.value
        if isinstance(held, ast.Name) and held.id == "settings":
            found.add(node.attr)
    return found


def test_every_tunable_setting_is_read_through_the_store():
    straying: dict[str, set[str]] = {}
    for path in sorted(Path("app").rglob("*.py")):
        if path in ALLOWED:
            continue
        reads = _reads(path)
        if reads:
            straying[str(path)] = reads

    assert not straying, (
        "these read a changeable setting off the configuration, so an "
        "administrator changing it would move nothing: "
        + "; ".join(f"{where}: {', '.join(sorted(names))}" for where, names in straying.items())
        + ". Read it through preferences.value instead."
    )


def test_the_guard_can_see_a_stray_read(tmp_path):
    """Or it would pass for ever after somebody broke the arrangement."""
    strayed = tmp_path / "stray.py"
    strayed.write_text("from app.core.config import settings\nlimit = settings.max_upload_mb\n")
    assert _reads(strayed) == {"max_upload_mb"}


def test_no_property_on_the_configuration_reads_a_changeable_setting():
    """A derived property is a read site the store cannot reach.

    The upload limit was first told to people through `settings.max_upload_label`,
    a property that read the raw field. An administrator who lowered the limit
    was then refused for exceeding a ceiling that was no longer in force: the
    check obeyed the new value and the sentence quoted the old one. Anything
    derived from a changeable setting has to be derived where the changes are.
    """
    import inspect

    from app.core.config import Settings

    straying: dict[str, set[str]] = {}
    for name, attribute in vars(Settings).items():
        if not isinstance(attribute, property) or attribute.fget is None:
            continue
        source = inspect.getsource(attribute.fget)
        tree = ast.parse(textwrap.dedent(source))
        reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in TUNABLE
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        if reads:
            straying[name] = reads

    assert not straying, (
        "these properties read a changeable setting off the configuration, so "
        "what they derive would ignore an administrator's change: "
        + "; ".join(f"{where}: {', '.join(sorted(names))}" for where, names in straying.items())
        + ". Derive it in preferences instead, like upload_label does."
    )
