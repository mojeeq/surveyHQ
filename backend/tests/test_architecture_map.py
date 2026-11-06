"""The code map in the architecture guide is the code.

A map of the services is the first thing anybody reads to find their way
around, and it is the easiest documentation to leave behind: adding a module
is a pull request, mentioning it is a separate thought. It had drifted to
nineteen modules missing and one - an R workspace, replaced by the Stata
command box - that no longer exists, which is worse than no map, because a
reader who finds the first wrong entry cannot trust any of the rest.

Both directions are checked. Nothing in services/ is left out, and nothing
is named that is not there.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "backend/app/services"
GUIDE = ROOT / "docs/architecture.md"


def mapped() -> set[str]:
    """The .py files the guide's code map names."""
    text = GUIDE.read_text(encoding="utf-8")
    block = re.search(r"```\nbackend/app/\n(.*?)```", text, re.S)
    assert block, "the code map is no longer a fenced block starting backend/app/"
    return set(re.findall(r"(\w+\.py)", block.group(1)))


def present() -> set[str]:
    return {
        path.name
        for path in SERVICES.glob("*.py")
        if path.name != "__init__.py"
    }


def test_every_service_is_on_the_map():
    missing = sorted(present() - mapped())
    assert not missing, (
        "services the architecture guide does not mention: "
        + ", ".join(missing)
        + ". Add a line to the code map in docs/architecture.md."
    )


def test_the_map_names_nothing_that_does_not_exist():
    """An entry for a module that was deleted is the one that misleads most."""
    anywhere = {path.name for path in (ROOT / "backend/app").rglob("*.py")}
    phantom = sorted(mapped() - anywhere)
    assert not phantom, (
        "the architecture guide names modules that are not there: "
        + ", ".join(phantom)
    )
