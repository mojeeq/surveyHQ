"""How an exported dashboard is dressed.

A board that somebody has put a ministry's colours and logo on is the board
they want to hand to a minister. Until now the export dropped all of it: the
appearance travelled in the payload and nothing read it, so a carefully dressed
dashboard arrived as grey cards on white.

This turns the same appearance into plain CSS for the exported file. The two
helpers the application draws with - `bandStyle` and `canvasStyle` in
`DashboardAppearance.tsx` - are followed exactly rather than approximated,
including the sheen over a masthead and the veil over a background image,
because a board that is nearly right is worse than one that is plainly plain:
nobody can tell whether they are looking at a fault or a decision.

Images are carried in the file as base64, for the same reason the fonts are.
A background served from a URL is a background that will not be there.
"""

from __future__ import annotations

import base64
from typing import Any

from app.services import export_fonts
from app.services.dashboard_assets import background_file

# How large an uploaded image may be before the export keeps the colour and
# leaves the picture behind.
#
# Uploads are allowed up to 8 MB, and base64 adds a third again, so carrying
# the largest of them would put over 10 MB into a file whose whole purpose is
# being emailed. Three is enough for any photograph anybody has put behind a
# dashboard and still leaves the file sendable.
MAX_IMAGE_BYTES = 3 * 1024 * 1024

# The gloss the application lays over a masthead. Same curve as its cards, in
# the same property as the colour, because two background-images cannot both
# win - see bandStyle.
SHEEN = (
    "linear-gradient(to bottom, rgba(255,255,255,0.16) 0%, rgba(255,255,255,0.03) 46%, "
    "rgba(0,0,0,0.02) 54%, rgba(0,0,0,0.07) 100%)"
)


def _clean(value: Any) -> str:
    """A colour or length from stored JSON, safe to put in a stylesheet.

    Appearance reaches this through a JSON column an editor can PATCH, so a
    value could carry a brace or a semicolon and close the rule it sits in.
    Anything with a character CSS treats as structure is dropped rather than
    escaped: there is no legitimate colour that needs one.
    """
    text = str(value or "").strip()
    if not text or len(text) > 64:
        return ""
    if any(ch in text for ch in "{};<>\\\"'()"):
        return ""
    return text


def _number(value: Any, low: float, high: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return max(low, min(high, number))


def is_dark(colour: str) -> bool:
    """Whether text on this colour has to be light.

    Rec. 709 luma, the same threshold the application uses: the eye takes green
    as much brighter than blue at the same number, so averaging the channels
    would call #0000ff light.
    """
    hex_part = _clean(colour).lstrip("#")
    if len(hex_part) != 6:
        return False
    try:
        red, green, blue = (int(hex_part[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255 < 0.5


def band(from_colour: Any, to_colour: Any, angle: Any, gloss: bool = True) -> str:
    """A flat colour or a two-colour gradient, as one `background` shorthand."""
    start = _clean(from_colour)
    if not start:
        return ""
    end = _clean(to_colour)
    turn = _number(angle, 0, 360)
    # ":g" rather than str(): _number returns a float, and a stylesheet saying
    # 90.0deg where the platform says 90deg is a difference someone will chase.
    colour = (
        f"linear-gradient({turn if turn is not None else 135:g}deg, {start}, {end})"
        if end
        else f"linear-gradient({start}, {start})"
    )
    layers = f"{SHEEN},{colour}" if gloss else colour
    return f"background-color:{start};background-image:{layers};"


def image_data_url(dashboard: Any, kind: str) -> str:
    """One of the dashboard's images as a data URL, or empty.

    Empty covers every way this can come to nothing - no image set, the file
    gone from disk, or one too large to put in a file meant for an inbox - and
    the caller treats them the same way, because the reader sees the same thing
    in each case.
    """
    appearance = dashboard.appearance or {}
    stored = appearance.get("logo_image" if kind == "logo" else "background_image")
    found = background_file(dashboard.id, stored, kind=kind)
    if found is None:
        return ""
    path, content_type = found
    try:
        if path.stat().st_size > MAX_IMAGE_BYTES:
            return ""
        data = path.read_bytes()
    except OSError:
        return ""
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def canvas(appearance: dict[str, Any], image: str) -> str:
    """The board's own ground: a colour, an image, and the veil over it."""
    colour = _clean(appearance.get("background_color"))
    if not colour and not image:
        return ""
    rules = []
    if colour:
        rules.append(f"background-color:{colour};")
    if image:
        fit = str(appearance.get("background_fit") or "cover")
        if fit not in ("cover", "contain", "tile"):
            fit = "cover"
        fade = _number(appearance.get("fade"), 0, 1) or 0
        # The veil is a gradient of one colour laid over the image in the same
        # property, which is how an image is dimmed without a second element
        # between the background and the widgets.
        veil = (
            f"linear-gradient(rgba(255,255,255,{fade}),rgba(255,255,255,{fade})),"
            if fade > 0
            else ""
        )
        rules.append(f"background-image:{veil}url({image});")
        rules.append(f"background-size:{'auto' if fit == 'tile' else fit};")
        rules.append(f"background-repeat:{'repeat' if fit == 'tile' else 'no-repeat'};")
        rules.append("background-position:center;")
    return "".join(rules)


def stylesheet(dashboard: Any, background: str) -> str:
    """Every appearance rule for this board, as one block of CSS.

    Written against the class names the exported page already uses, so the
    page's own script stays a page-drawing script rather than becoming a second
    place appearance is decided.
    """
    appearance: dict[str, Any] = dashboard.appearance or {}
    out: list[str] = []

    ground = band(
        appearance.get("page_background"),
        appearance.get("page_background_2"),
        appearance.get("page_angle"),
        gloss=False,
    )
    if ground:
        out.append(f"body{{{ground}}}")

    board = canvas(appearance, background)
    if board:
        # The board is its own surface inside the page, which is the shape the
        # application gives it once a ground is set behind it.
        out.append(f".wrap{{{board}border-radius:12px;padding:20px 18px 40px;}}")

    # Everything loose on the board - the title where no masthead covers it,
    # and the footer - reads against whatever is directly behind it. That is
    # the board's own canvas when one is set, and only the page ground when
    # there is no board colour at all. Getting this backwards is how the footer
    # ended up pale grey on pale paper.
    behind = appearance.get("background_color") if board else appearance.get("page_background")
    if is_dark(behind):
        out.append("footer.board{color:rgba(255,255,255,.65);}")
        if not appearance.get("header_background"):
            out.append(
                "header.board h1{color:#f4f5f7;}"
                "header.board p{color:rgba(244,245,247,.75);}"
            )

    masthead = band(
        appearance.get("header_background"),
        appearance.get("header_background_2"),
        appearance.get("header_angle"),
    )
    if masthead:
        out.append(
            f"header.board{{{masthead}border-radius:10px;padding:16px 18px;margin-bottom:6px;}}"
        )
        if is_dark(appearance.get("header_background")):
            out.append(
                "header.board h1{color:#f4f5f7;}"
                "header.board p{color:rgba(244,245,247,.75);}"
            )

    title_stack = export_fonts.stack_for(appearance.get("title_font"))
    if title_stack:
        out.append(f"header.board h1{{font-family:{title_stack};}}")

    title_size = _number(appearance.get("title_size"), 10, 96)
    if title_size:
        out.append(f"header.board h1{{font-size:{title_size:g}px;}}")
    title_colour = _clean(appearance.get("title_color"))
    if title_colour:
        out.append(f"header.board h1{{color:{title_colour};}}")
    if str(appearance.get("title_align")) == "center":
        out.append("header.board{text-align:center;}header.board .brand{justify-content:center;}")
    if appearance.get("header_rule"):
        out.append("header.board{border-bottom:1px solid var(--ink-200);padding-bottom:12px;}")

    tab_band = _clean(appearance.get("tab_background"))
    if tab_band:
        out.append(f".tabs{{background:{tab_band};border-radius:8px;padding:4px 6px;}}")
    tab_colour = _clean(appearance.get("tab_color")) or (
        "#f4f5f7" if (tab_band and is_dark(tab_band)) else ""
    )
    if tab_colour:
        # The chosen tab keeps its underline but takes the same ink, so a dark
        # band does not leave one tab legible and the rest not.
        out.append(
            f'.tabs button{{color:{tab_colour};opacity:.75;}}'
            f'.tabs button[aria-selected="true"]{{color:{tab_colour};opacity:1;'
            f"border-bottom-color:{tab_colour};}}"
        )

    filter_band = _clean(appearance.get("filter_background"))
    if filter_band:
        out.append(f".filters{{background:{filter_band};}}")
    filter_colour = _clean(appearance.get("filter_color")) or (
        "#f4f5f7" if (filter_band and is_dark(filter_band)) else ""
    )
    if filter_colour:
        out.append(f".filters label{{color:{filter_colour};}}")

    opacity = _number(appearance.get("widget_opacity"), 0, 1)
    if opacity is not None and opacity < 1:
        # The card's own paint, not its contents: `opacity` would fade the text
        # and the charts with it.
        out.append(f".card{{background-color:rgba(255,255,255,{opacity:g});}}")

    logo_height = _number(appearance.get("logo_height"), 8, 200)
    out.append(
        "header.board .brand{display:flex;align-items:center;gap:12px;}"
        f"header.board .brand img{{height:{logo_height or 40:g}px;width:auto;}}"
    )

    return "\n".join(out)


def look(dashboard: Any, logo: str) -> dict[str, Any]:
    """The few appearance facts the page's script has to act on itself.

    Everything that is only paint is in the stylesheet. What is left is
    structure: whether there is a logo to put in the header, and whether the
    description under the title was meant to be shown at all.
    """
    appearance: dict[str, Any] = dashboard.appearance or {}
    return {
        "logo": logo,
        "hide_subtitle": bool(appearance.get("hide_subtitle")),
        # Not drawn from here - the stylesheet sets the title's font. It is
        # carried so the export knows to embed that face as well as the ones
        # the widgets use.
        "title_stack": export_fonts.stack_for(appearance.get("title_font")),
    }
