"""The drawing libraries and the palette an exported dashboard carries.

The export is for opening where this platform is not reachable, so the thing
worth holding still is that it reaches for nothing. It used to fetch ECharts
and Leaflet from a CDN, which fails quietly rather than loudly: the page opens,
the tables still add up, and every chart on it has become a table of numbers,
because the drawing code falls back to a table when `window.echarts` is not
there. Nothing on the page says why.

The palette is the other half. A board carries the name of a chart theme; the
export was carrying that name and ignoring it, drawing instead from a private
list of its own that matched no theme the platform has.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from app.services import export_lib
from app.services.static_export import render_html

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
CHARTS_TS = FRONTEND / "src" / "lib" / "charts.ts"


def board(kinds: list[str], theme: str = "default") -> dict:
    """The smallest payload render_html will take, one widget per kind."""
    return {
        "name": "Fieldwork",
        "description": "",
        "generated_at": "2026-01-01T00:00:00",
        "theme": theme,
        "colors": export_lib.colors_for(theme),
        "appearance": {},
        "pages": [{"name": "Page 1"}],
        "groups": [],
        "filters": [],
        "widgets": [
            {
                "id": f"w{index}",
                "title": "Coverage",
                "type": kind,
                "kind": kind,
                "page": 0,
                "group_id": "",
                "layout": {},
                "style": {},
                "config": {},
            }
            for index, kind in enumerate(kinds)
        ],
    }


# --- nothing is fetched -----------------------------------------------------


def test_the_page_asks_the_network_for_nothing():
    """The one thing the whole exercise rests on.

    Not "no CDN" but no outside address at all: a stylesheet, an icon or a
    script from anywhere is a thing the file does not have when it is opened
    on a laptop in a district office.
    """
    html = render_html(board(["chart"]))
    outside = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', html)
    assert outside == []


def test_the_chart_library_travels_in_the_file():
    html = render_html(board(["chart"]))
    # A recognisable piece of the library itself, not merely a script tag.
    assert "echarts" in html
    assert len(html) > 900_000, "the chart library does not appear to be inlined"


# Matched against the libraries' own source rather than the word "leaflet",
# which the page's comments use to explain when the map is built.
MAP_CSS = ".leaflet-pane"
MAP_JS = "leaflet-container"


def test_a_board_with_no_map_does_not_carry_the_map_library():
    """160 KB in every file, for a board that would never execute a line of it."""
    html = render_html(board(["chart"]))
    assert MAP_CSS not in html
    assert MAP_JS not in html


def test_a_board_with_a_map_carries_the_map_library():
    html = render_html(board(["chart", "map"]))
    assert MAP_JS in html
    # Its stylesheet too: Leaflet lays its panes out in CSS, and without it the
    # tiles stack in a column down the page.
    assert MAP_CSS in html


def test_what_is_inlined_cannot_end_the_tag_it_is_inlined_in():
    """A library holding `</script>` would put the rest of itself on the screen."""
    for entry in export_lib.manifest():
        source = (export_lib.LIB / str(entry["file"])).read_text(encoding="utf-8")
        assert "</script" not in source.lower()
        assert "<!--" not in source


# --- vendored from the same packages the frontend builds against ------------


@pytest.mark.parametrize("entry", export_lib.manifest(), ids=lambda e: str(e["file"]))
def test_the_vendored_copy_is_the_package_it_claims_to_be(entry):
    """`npm run lib:sync` was run, and run against what is installed now.

    Skipped where node_modules is not there, which is the backend's own CI
    image: the check is only meaningful beside the frontend it copies from.
    """
    source = FRONTEND / "node_modules" / str(entry["package"])
    if not source.exists():
        pytest.skip("frontend/node_modules is not installed here")
    installed = json.loads((source / "package.json").read_text())["version"]
    assert installed == entry["version"], (
        f"{entry['package']} is {installed} but the export carries "
        f"{entry['version']}. Run `npm run lib:sync` in frontend/."
    )
    carried = (export_lib.LIB / str(entry["file"])).read_bytes()
    assert hashlib.sha256(carried).hexdigest() == entry["sha256"]


# --- the board's own colours ------------------------------------------------


def test_every_theme_the_interface_offers_is_carried():
    """The table is compiled out of the frontend, so it cannot drift from it."""
    declared = set(re.findall(r"^  (\w+): \{$", CHARTS_TS.read_text(), re.M))
    if not declared:
        pytest.skip("the theme table is not laid out as expected any more")
    assert declared == set(export_lib.themes())


def test_a_board_exports_in_the_colours_it_is_drawn_in():
    for name, colors in export_lib.themes().items():
        assert export_lib.colors_for(name) == colors
    # Each theme is the same hues in a different order, so a payload that
    # ignored the name would still look plausible - the order is the whole
    # difference, and it is what decides which series is which colour.
    assert export_lib.colors_for("vivid") != export_lib.colors_for("default")


def test_a_theme_that_no_longer_exists_falls_back_rather_than_failing():
    """A board saved against a renamed theme still exports, as it still draws."""
    assert export_lib.colors_for("a-theme-since-removed") == export_lib.themes()["default"]
    assert export_lib.colors_for(None) == export_lib.themes()["default"]


def test_the_colours_reach_the_page():
    html = render_html(board(["chart"], theme="vivid"))
    assert export_lib.colors_for("vivid")[0] in html
