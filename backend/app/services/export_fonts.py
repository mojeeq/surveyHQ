"""The bundled fonts an exported dashboard carries with it.

A standalone export is one HTML file meant to open on a laptop in a meeting
room with nothing behind it - no platform, often no network. A font it names
but does not carry is a font it will not have, so the faces a board is actually
set in are embedded in the file itself, base64 inside a `@font-face`.

Only the faces in use. Embedding all seven would add about 700 KB of base64 to
every export, most of it never drawn, and an export is something people email.
A board set in the interface font carries no font data at all.

The files come from `export_assets/fonts/`, put there by
`scripts/sync-export-fonts.mjs` from the same packages the application serves,
so an exported board and the board it was exported from are in the same face
rather than two cuts of a similar one.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path(__file__).parent / "export_assets" / "fonts"
MANIFEST = FONT_DIR / "fonts.json"


@lru_cache(maxsize=1)
def _manifest() -> list[dict[str, object]]:
    """Every bundled face, or nothing if the sync script has not been run.

    Missing files are not an error worth failing an export over: the reader
    gets the fallback face, which is what they got before any of this existed.
    """
    if not MANIFEST.is_file():
        return []
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


def bundled_families() -> set[str]:
    """The family names an export can carry."""
    return {str(entry["family"]) for entry in _manifest()}


def families_in(stack: str) -> list[str]:
    """The bundled families a CSS font stack names, in the order it names them.

    A stack is a comma-separated list where a family whose name has a space in
    it is quoted, which is every bundled one. Matching on the whole stack would
    miss a hand-edited one that puts a fallback first, so each name is taken on
    its own.
    """
    available = bundled_families()
    found: list[str] = []
    for part in stack.split(","):
        name = part.strip().strip("\"'").strip()
        if name in available and name not in found:
            found.append(name)
    return found


def collect(stacks: list[str | None]) -> list[str]:
    """Which bundled families this set of font stacks needs, deduplicated."""
    wanted: list[str] = []
    for stack in stacks:
        if not stack:
            continue
        for family in families_in(str(stack)):
            if family not in wanted:
                wanted.append(family)
    return wanted


def css_for(families: list[str]) -> str:
    """`@font-face` rules for these families, each file inlined as base64.

    Returns an empty string when nothing is wanted, so the caller can drop it
    straight into the template either way.
    """
    if not families:
        return ""
    rules: list[str] = []
    for entry in _manifest():
        family = str(entry["family"])
        if family not in families:
            continue
        path = FONT_DIR / str(entry["file"])
        try:
            data = path.read_bytes()
        except OSError:
            # A file named in the manifest but not on disk. The face falls back
            # rather than the export failing.
            continue
        encoded = base64.b64encode(data).decode("ascii")
        rules.append(
            "@font-face{"
            f"font-family:'{family}';"
            "font-style:normal;"
            "font-display:swap;"
            f"font-weight:{entry['weight']};"
            f"src:url(data:font/woff2;base64,{encoded}) format('woff2');"
            "}"
        )
    return "\n".join(rules)
