"""The ready-made grounds, and the two copies of them staying one thing.

A board's ground is CSS rather than a picture, which is what lets an exported
file carry it. The application draws it from a TypeScript table in the browser
and the export draws it from a Python one on the server, because neither can
read the other's at the moment it needs it.

Two tables is two chances to be wrong, and the way it would be wrong is the
worst kind: a board that looks one way on screen and arrives looking another,
with nothing failing anywhere. So the TypeScript is read here and compared
with the Python, down to the last rgba.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services import export_appearance
from app.services.export_backgrounds import GROUNDS, ground

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "frontend/src/lib/backgrounds.ts"

FIELD = re.compile(r"^    (\w+):\s*(.*)$")
QUOTED = re.compile(r"'([^']*)'")


def from_typescript() -> dict[str, dict[str, str]]:
    """The grounds as the application has them.

    Read rather than imported: the value of a guard that parses the real file
    is that nobody can satisfy it by updating a copy of the file.
    """
    source = TABLE.read_text(encoding="utf-8")
    body = source[
        source.index("export const BACKGROUNDS") : source.index("/** One ground by id")
    ]
    out: dict[str, dict[str, str]] = {}
    one: dict[str, str] | None = None
    field = ""
    buffer: list[str] = []

    def close() -> None:
        nonlocal field, buffer
        if one is not None and field:
            one[field] = "".join(QUOTED.findall("".join(buffer)))
        field, buffer = "", []

    for line in body.splitlines():
        if line.strip() == "{":
            one = {}
            continue
        if line.strip().startswith("},"):
            close()
            if one:
                out[one["id"]] = one
            one = None
            continue
        if one is None:
            continue
        found = FIELD.match(line)
        if found:
            close()
            field = found.group(1)
            buffer = [found.group(2)]
        elif field:
            buffer.append(line)
    return out


def test_the_two_tables_hold_the_same_grounds():
    assert set(from_typescript()) == set(GROUNDS), (
        "the grounds in frontend/src/lib/backgrounds.ts and "
        "backend/app/services/export_backgrounds.py are no longer the same set"
    )


def test_every_ground_is_drawn_the_same_way_in_both():
    for name, theirs in from_typescript().items():
        mine = GROUNDS[name]
        assert mine["tint"] == theirs["tint"], name
        assert mine["layers"] == theirs["layers"], name
        assert mine.get("size", "") == theirs.get("size", ""), name


def test_a_ground_is_css_rather_than_a_file():
    """A url() here would be a request the exported file cannot make."""
    for name, one in GROUNDS.items():
        assert "url(" not in one["layers"], name
        assert "gradient(" in one["layers"], name


def test_a_ground_cannot_close_the_rule_it_sits_in():
    """Appearance reaches the stylesheet through a JSON column an editor PATCHes."""
    for name, one in GROUNDS.items():
        assert "}" not in one["layers"] and ";" not in one["layers"], name


# --- In the exported stylesheet ---------------------------------------------


class _Board:
    def __init__(self, appearance: dict[str, Any]):
        self.id = "board"
        self.appearance = appearance
        self.name = "Board"


def test_the_board_carries_its_ground_into_the_file():
    css = export_appearance.canvas({"background_pattern": "graph"}, "")

    assert f"background-image:{GROUNDS['graph']['layers']};" in css
    # Without its cell size a squared pattern is one line across the top.
    assert f"background-size:{GROUNDS['graph']['size']};" in css
    assert f"background-color:{GROUNDS['graph']['tint']};" in css


def test_a_chosen_colour_wins_over_the_ground_s_own_tint():
    """The ground is a starting point; the colour picker underneath is not."""
    css = export_appearance.canvas(
        {"background_pattern": "graph", "background_color": "#101010"}, ""
    )

    assert "background-color:#101010;" in css
    assert GROUNDS["graph"]["tint"] not in css


def test_an_uploaded_image_stands_in_front_of_the_ground():
    css = export_appearance.canvas(
        {"background_pattern": "carbon", "background_color": "#111418"}, "data:image/png;base64,AA"
    )

    assert "url(data:image/png;base64,AA)" in css
    assert GROUNDS["carbon"]["layers"] not in css


def test_a_ground_this_version_no_longer_has_is_simply_not_drawn():
    """A board saved against an older list must still export, plainly."""
    assert export_appearance.canvas({"background_pattern": "ziggurat"}, "") == ""
    assert ground("ziggurat") is None


def test_a_dark_ground_lightens_the_title_and_the_footer():
    """The title reads against the board's ground when nothing else is behind it."""
    css = export_appearance.stylesheet(_Board({"background_pattern": "carbon"}), "")

    assert "footer.board{color:rgba(255,255,255,.65);}" in css
    assert "header.board h1{color:#f4f5f7;}" in css
