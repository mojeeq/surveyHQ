"""The drawing libraries an exported dashboard carries inside itself.

The export is for opening where this platform is not reachable, and until now
it fetched ECharts and Leaflet from a CDN. That failed quietly rather than
loudly: the page opened, the tables still added up, and every chart on it had
become a table of numbers, because the drawing code falls back to a table when
`window.echarts` is missing. A ministry network that blocks jsdelivr and the
laptop carried to the meeting both produced that page, and nothing on it said
why.

So the libraries travel in the file. ECharts always, because a board without a
chart is rare and the code cannot know ahead of the widgets which ones will
draw. Leaflet only when the board carries a map, because it is 160 KB that a
board with no map would never execute - the same rule the bundled fonts follow.

A map still needs the internet for its tiles. That is not something a file can
carry: the basemap is millions of images on somebody else's server. The charts,
which are drawn from numbers already in the file, no longer do.

The files themselves are vendored by `scripts/sync-export-lib.mjs`, from the
same node_modules the frontend builds against, so an exported chart is drawn by
the version of ECharts the platform draws with rather than whichever one a CDN
URL was pinned to years earlier.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LIB = Path(__file__).parent / "export_assets" / "lib"
MANIFEST = LIB / "lib.json"
THEMES = LIB / "themes.json"


class MissingLibrary(RuntimeError):
    """The vendored copy is not there, so an export would be chartless."""


@lru_cache(maxsize=1)
def manifest() -> list[dict[str, object]]:
    """What was vendored, as the sync script recorded it."""
    if not MANIFEST.exists():
        raise MissingLibrary(
            f"{MANIFEST} is missing. Run `npm run lib:sync` in frontend/."
        )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _source(name: str) -> str:
    path = LIB / name
    if not path.exists():
        raise MissingLibrary(
            f"{path} is missing. Run `npm run lib:sync` in frontend/."
        )
    return path.read_text(encoding="utf-8")


def head_for(needs_map: bool) -> str:
    """The stylesheets the page needs, ready to drop into <head>.

    Leaflet's sheet names three images - the marker icon and the layers control
    - which this page never asks for: it draws circle markers and offers no
    layer switcher. They are left in the sheet rather than picked out of it,
    because editing somebody else's CSS to save three lines is how a later
    upgrade quietly breaks.
    """
    if not needs_map:
        return ""
    return f"<style>\n{_source('leaflet.css')}\n</style>"


def scripts_for(needs_map: bool) -> str:
    """The libraries the page needs, ready to drop in before its own script."""
    names = ["echarts.js"] + (["leaflet.js"] if needs_map else [])
    return "\n".join(f"<script>\n{_source(name)}\n</script>" for name in names)


def bytes_for(needs_map: bool) -> int:
    """How much of an export is library, for anything that wants to say so."""
    wanted = {"always"} | ({"map"} if needs_map else set())
    return sum(int(entry["bytes"]) for entry in manifest() if entry["when"] in wanted)


@lru_cache(maxsize=1)
def themes() -> dict[str, list[str]]:
    """The chart palettes, as the frontend's own theme table defines them."""
    if not THEMES.exists():
        raise MissingLibrary(
            f"{THEMES} is missing. Run `npm run lib:sync` in frontend/."
        )
    return json.loads(THEMES.read_text(encoding="utf-8"))


def colors_for(theme: str | None) -> list[str]:
    """The colours a board set to `theme` is drawn in.

    An unknown name falls back to the default rather than raising: a board
    saved against a theme that was later renamed should still export, and in
    the colours the platform is showing it in, which is the same fallback the
    interface makes.
    """
    table = themes()
    return list(table.get(theme or "default") or table["default"])
