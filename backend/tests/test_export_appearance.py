"""How an exported dashboard is dressed.

A board somebody has put a ministry's colours and logo on is the board they
want to hand to a minister. The export used to drop all of it - the appearance
travelled in the payload and nothing read it - so a dressed dashboard arrived
as grey cards on white.

What is held still here: that each setting reaches the file, that the file is
still standalone when it does, and that a value which arrived through a JSON
column cannot close the rule it is written into.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.services import export_appearance
from app.services.static_export import appearance_css, render_html
from tests.test_export_fonts import board


def dashboard(**appearance: object) -> SimpleNamespace:
    """The two attributes the appearance code reads off a dashboard."""
    return SimpleNamespace(id="dash-1", appearance=appearance)


# --- the ground, the board, the masthead -----------------------------------


def test_an_undressed_board_gets_no_rules_at_all():
    """A board nobody has styled must not gain a stylesheet full of defaults."""
    css = appearance_css(dashboard())
    # Only the logo sizing rule, which is harmless and always present.
    assert "body{" not in css
    assert ".wrap{" not in css
    assert "header.board{" not in css


def test_the_page_ground_reaches_the_body():
    css = appearance_css(dashboard(page_background="#0d47a1"))
    assert "body{background-color:#0d47a1;" in css


def test_two_colours_make_a_gradient_and_one_does_not():
    flat = appearance_css(dashboard(page_background="#0d47a1"))
    assert "linear-gradient(#0d47a1, #0d47a1)" in flat

    ramp = appearance_css(
        dashboard(page_background="#0d47a1", page_background_2="#2f6fd0", page_angle=90)
    )
    assert "linear-gradient(90deg, #0d47a1, #2f6fd0)" in ramp


def test_a_masthead_carries_the_sheen_and_the_ground_does_not():
    """Same rule as the platform: the band is glossed, the page behind it is not."""
    head = appearance_css(dashboard(header_background="#1565c0"))
    assert export_appearance.SHEEN in head

    ground = appearance_css(dashboard(page_background="#1565c0"))
    assert export_appearance.SHEEN not in ground


def test_a_dark_masthead_lightens_its_own_title():
    dark = appearance_css(dashboard(header_background="#0d47a1"))
    assert "header.board h1{color:#f4f5f7;}" in dark

    light = appearance_css(dashboard(header_background="#e3f2fd"))
    assert "#f4f5f7" not in light


# --- the title --------------------------------------------------------------


def test_title_size_colour_and_alignment():
    css = appearance_css(
        dashboard(title_size=40, title_color="#0d47a1", title_align="center")
    )
    assert "font-size:40px" in css
    assert "color:#0d47a1" in css
    assert "text-align:center" in css


def test_a_title_font_id_becomes_the_stack_the_interface_uses():
    """The dashboard stores an id; the file needs the CSS behind it."""
    css = appearance_css(dashboard(title_font="source-serif"))
    assert 'font-family:"Source Serif 4 Variable"' in css


def test_the_title_font_is_carried_in_the_file():
    """The whole point: a face named in the stylesheet has to be embedded too.

    Before this, the font scan only looked at widgets, so a board whose title
    was the only thing in Source Serif named the face and carried nothing.
    """
    payload = board(None)
    payload["look"] = {
        "logo": "",
        "hide_subtitle": False,
        "title_stack": '"Source Serif 4 Variable", Georgia, serif',
    }
    html = render_html(payload, appearance_css(dashboard(title_font="source-serif")))
    assert "@font-face{font-family:'Source Serif 4 Variable'" in html
    assert "data:font/woff2;base64," in html


def test_an_unknown_font_id_sets_no_family():
    assert "font-family" not in appearance_css(dashboard(title_font="comic-sans"))


# --- tabs, filters, cards ---------------------------------------------------


def test_a_dark_tab_band_gets_readable_tabs_without_being_asked():
    css = appearance_css(dashboard(tab_background="#0d47a1"))
    assert ".tabs{background:#0d47a1" in css
    assert "#f4f5f7" in css


def test_an_explicit_tab_colour_wins_over_the_automatic_one():
    css = appearance_css(dashboard(tab_background="#0d47a1", tab_color="#ffd54f"))
    assert "#ffd54f" in css
    assert ".tabs button{color:#f4f5f7" not in css


def test_widget_opacity_fades_the_card_and_not_its_contents():
    """`opacity` would take the text and the charts down with the paint."""
    css = appearance_css(dashboard(widget_opacity=0.7))
    assert ".card{background-color:rgba(255,255,255,0.7);}" in css
    assert "opacity:0.7" not in css


def test_a_fully_opaque_card_needs_no_rule():
    assert ".card{" not in appearance_css(dashboard(widget_opacity=1))


# --- values that arrived through a JSON column ------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "#fff;} body{display:none",
        "red<script>alert(1)</script>",
        "url(https://tracker.example/pixel)",
        'red" onload="x',
        "#" + "a" * 200,
    ],
)
def test_a_colour_that_tries_to_close_its_rule_is_dropped(hostile: str):
    """Appearance is a JSON column an editor can PATCH, so it is checked.

    A stylesheet is not HTML-escaped on its way into the file, so a value
    carrying a brace, a semicolon or a bracket would end the rule it sits in
    and start something else.
    """
    css = appearance_css(dashboard(page_background=hostile, title_color=hostile))
    assert "display:none" not in css
    assert "<script" not in css
    assert "tracker.example" not in css
    assert "onload" not in css


def test_a_hostile_value_does_not_reach_the_rendered_file():
    html = render_html(board(None), appearance_css(dashboard(page_background="#fff;}body{display:none")))
    assert "display:none" not in html


@pytest.mark.parametrize("fade", ["nonsense", None, float("nan"), 99, -4])
def test_a_fade_that_is_not_a_fraction_is_brought_back_into_range(fade: object):
    css = export_appearance.canvas(
        {"background_color": "#fff", "fade": fade}, "data:image/png;base64,AAA"
    )
    found = re.findall(r"rgba\(255,255,255,([\d.]+)\)", css)
    for value in found:
        assert 0 <= float(value) <= 1


# --- images -----------------------------------------------------------------


def test_an_image_too_large_to_email_is_left_behind(tmp_path, monkeypatch):
    """The colour still arrives; the photograph does not.

    Uploads are allowed up to 8 MB and base64 adds a third again, so the
    largest of them would put over 10 MB into a file whose purpose is being
    sent to somebody.
    """
    big = tmp_path / "dash-1.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (export_appearance.MAX_IMAGE_BYTES + 1))
    monkeypatch.setattr(
        export_appearance, "background_file", lambda *a, **k: (big, "image/png")
    )
    board_with_image = dashboard(background_image="dash-1.png", background_color="#0d47a1")
    assert export_appearance.image_data_url(board_with_image, "background") == ""
    css = appearance_css(board_with_image)
    assert "background-color:#0d47a1" in css
    assert "base64" not in css


def test_an_image_that_fits_is_carried_as_a_data_url(tmp_path, monkeypatch):
    small = tmp_path / "dash-1.png"
    small.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setattr(
        export_appearance, "background_file", lambda *a, **k: (small, "image/png")
    )
    css = appearance_css(dashboard(background_image="dash-1.png", fade=0.4))
    assert "url(data:image/png;base64," in css
    assert "rgba(255,255,255,0.4)" in css


def test_a_missing_file_is_not_an_error(monkeypatch):
    """A board whose image was deleted still exports, without the image."""
    monkeypatch.setattr(export_appearance, "background_file", lambda *a, **k: None)
    assert export_appearance.image_data_url(dashboard(logo_image="gone.png"), "logo") == ""


# --- the file as a whole ----------------------------------------------------


def test_the_stylesheet_reaches_the_file_and_the_placeholder_is_gone():
    html = render_html(board(None), appearance_css(dashboard(page_background="#0d47a1")))
    assert "/*__LOOK__*/" not in html
    assert "body{background-color:#0d47a1;" in html


def test_an_undressed_board_leaves_no_placeholder_behind():
    html = render_html(board(None))
    assert "/*__LOOK__*/" not in html


def test_the_stylesheet_is_not_also_carried_in_the_json():
    """A background image is already base64; through the JSON as well it is
    the same megabyte in the file twice."""
    css = appearance_css(dashboard(page_background="#0d47a1"))
    html = render_html(board(None), css)
    assert html.count("background-color:#0d47a1") == 1


# --- what is actually behind the loose text ---------------------------------
#
# The footer and the title sit inside the board, not on the page ground, so
# they read against the board's own canvas whenever one is set. Reading the
# ground instead is how the footer came out pale grey on pale paper.


def test_a_light_board_on_a_dark_ground_keeps_dark_footer_text():
    """The board is what the footer sits on, so the ground does not decide."""
    css = appearance_css(dashboard(page_background="#0b2545", background_color="#f7f9fc"))
    assert "footer.board{color:rgba(255,255,255,.65);}" not in css


def test_a_dark_board_lightens_the_footer_whatever_the_ground_is():
    css = appearance_css(dashboard(page_background="#f7f9fc", background_color="#0b2545"))
    assert "footer.board{color:rgba(255,255,255,.65);}" in css


def test_a_dark_ground_with_no_board_colour_does_lighten_the_footer():
    """With no board canvas the footer really is on the ground."""
    css = appearance_css(dashboard(page_background="#0b2545"))
    assert "footer.board{color:rgba(255,255,255,.65);}" in css


def test_a_dark_board_lightens_the_title_only_when_no_masthead_covers_it():
    bare = appearance_css(dashboard(background_color="#0b2545"))
    assert "header.board h1{color:#f4f5f7;}" in bare

    # With a masthead the title sits on the band, which decides for itself.
    covered = appearance_css(
        dashboard(background_color="#0b2545", header_background="#ffd54f")
    )
    assert covered.count("header.board h1{color:#f4f5f7;}") == 0
