"""The fonts an exported dashboard carries.

Two things are worth holding still here. A board set in a bundled face has to
arrive with that face inside the file, because the file is for opening where
this platform is not reachable. And a board that uses none has to carry none,
because an export is something people email and seven embedded families is
most of a megabyte of base64 that nothing on the page ever draws.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re

import pytest

from app.services import export_fonts
from app.services.static_export import render_html

INTER = '"Inter Variable", system-ui, -apple-system, "Segoe UI", sans-serif'
PLEX_SERIF = '"IBM Plex Serif", Georgia, "Times New Roman", serif'
SYSTEM_ONLY = 'Georgia, "Times New Roman", "Nimbus Roman", serif'


def board(*font_stacks: str | None) -> dict:
    """The smallest payload render_html will take, one widget per stack."""
    return {
        "name": "Fieldwork",
        "description": "",
        "generated_at": "2026-01-01T00:00:00",
        "theme": "default",
        "appearance": {},
        "pages": [{"name": "Page 1"}],
        "groups": [],
        "filters": [],
        "widgets": [
            {
                "id": f"w{index}",
                "title": "Coverage",
                "type": "chart",
                "page": 0,
                "group_id": "",
                "layout": {},
                "style": {} if stack is None else {"font_family": stack},
                "config": {},
            }
            for index, stack in enumerate(font_stacks)
        ],
    }


def faces(html: str) -> list[str]:
    """The font families the rendered page declares."""
    return re.findall(r"@font-face\{font-family:'([^']+)'", html)


# --- what gets carried ------------------------------------------------------


def test_a_board_set_in_a_bundled_font_carries_it():
    html = render_html(board(INTER))
    assert faces(html) == ["Inter Variable", "Inter Variable"], (
        "latin and latin-ext, which is where the macrons Fijian needs live"
    )
    assert "data:font/woff2;base64," in html


def test_a_board_that_uses_no_bundled_font_carries_none():
    """The size of an export matters: it is a thing people send by email."""
    plain = render_html(board(None, SYSTEM_ONLY))
    assert faces(plain) == []
    assert "data:font/woff2" not in plain
    # And the difference is the whole point of embedding only what is used.
    assert len(render_html(board(INTER))) > len(plain) + 100_000


def test_only_the_families_in_use_are_carried():
    html = render_html(board(PLEX_SERIF))
    assert set(faces(html)) == {"IBM Plex Serif"}
    assert "Inter Variable" not in html


def test_two_widgets_in_the_same_font_carry_it_once():
    once = render_html(board(INTER))
    twice = render_html(board(INTER, INTER))
    assert faces(twice) == faces(once)


def test_several_fonts_are_all_carried():
    html = render_html(board(INTER, PLEX_SERIF, SYSTEM_ONLY))
    assert set(faces(html)) == {"Inter Variable", "IBM Plex Serif"}


# --- reading a stack --------------------------------------------------------


def test_a_family_is_found_wherever_it_sits_in_the_stack():
    """A stack edited by hand can put a fallback first."""
    assert export_fonts.families_in(INTER) == ["Inter Variable"]
    assert export_fonts.families_in('Georgia, "Inter Variable", serif') == [
        "Inter Variable"
    ]
    assert export_fonts.families_in("Georgia, serif") == []


def test_a_static_face_declares_each_weight_it_ships():
    """IBM Plex Serif has no variable build, so it comes as two files."""
    css = export_fonts.css_for(["IBM Plex Serif"])
    assert sorted(re.findall(r"font-weight:(\d+)", css)) == ["400", "600"]


def test_nothing_wanted_means_no_style_at_all():
    assert export_fonts.css_for([]) == ""


# --- the files themselves ---------------------------------------------------


def test_every_file_in_the_manifest_is_present_and_unchanged():
    """Fails when scripts/sync-export-fonts.mjs has not been run after a change.

    The backend and the frontend are separate images, so these files are a copy
    of what the application serves. A copy that has drifted is worse than no
    copy: the exported board would be in a different cut of the same face.
    """
    manifest = json.loads(export_fonts.MANIFEST.read_text(encoding="utf-8"))
    assert manifest, "no fonts synced; run npm run fonts:sync in frontend/"
    for entry in manifest:
        path = export_fonts.FONT_DIR / entry["file"]
        assert path.is_file(), f"{entry['file']} is in the manifest but not on disk"
        data = path.read_bytes()
        assert len(data) == entry["bytes"], f"{entry['file']} has changed size"
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], (
            f"{entry['file']} does not match the manifest; re-run the sync script"
        )


def test_the_families_are_the_ones_the_interface_offers():
    """The catalogue in frontend/src/lib/fonts.ts, read from the file itself.

    Held together by a test rather than by a build step: the two lists live in
    different languages and nothing else would notice them drifting apart.
    """
    catalogue = (
        export_fonts.FONT_DIR.parents[4] / "frontend" / "src" / "lib" / "fonts.ts"
    ).read_text(encoding="utf-8")
    named = set(re.findall(r'^\s*family: "([^"]+)",', catalogue, re.MULTILINE))
    assert named == export_fonts.bundled_families()


@pytest.mark.parametrize("family", sorted(export_fonts.bundled_families()))
def test_each_face_embeds_as_a_real_woff2(family: str):
    """Decoded, the payload has to start with wOF2 rather than be any old bytes."""
    css = export_fonts.css_for([family])
    for blob in re.findall(r"base64,([A-Za-z0-9+/=]+)\)", css):
        assert base64.b64decode(blob)[:4] == b"wOF2"
