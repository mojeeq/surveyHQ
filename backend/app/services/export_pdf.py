"""A board as a PDF, printed by a browser.

The exported web page already carries everything it needs - its numbers, its
fonts, the libraries that draw its charts - and already has a print layout:
margins, no tab strip, the filters printed as the values they were set to, and
each card kept whole across the page breaks. A PDF is that page printed, so
that is what this does rather than laying a board out a second time. Two
layouts to keep in step would drift apart within a release or two, and the one
nobody looks at would be the one that drifted.

A board with several pages is several tabs in one file, and only the tab in
front is in the document at any moment, so each is printed in turn and the
sheets are put together at the end.

The browser is given no network at all: every request but the file itself is
refused. A map's basemap is the only thing that wants one, the export already
says it needs the internet for that, and a renderer that hangs for thirty
seconds on a server with no route out is worse than a map with no tiles.
"""

from __future__ import annotations

import io
import tempfile
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: How long the whole printing may take. A board of fifty widgets over a
#: census is seconds, not minutes; past this something is wrong and a request
#: held open is worse than an error that says so.
TIMEOUT_MS = 120_000

#: Wide enough that a twelve-column board is laid out as a board rather than
#: collapsing to the narrow stack the stylesheet falls back to under 781px.
VIEWPORT = {"width": 1440, "height": 1000}


@lru_cache(maxsize=1)
def _playwright_browser() -> str:
    """Where Playwright keeps its own chromium, or empty if it has none.

    Asking costs a subprocess, so it is asked once: a browser appearing on a
    running server means somebody has installed one, and installing one means
    a restart of this one way or another.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as driver:
            return str(driver.chromium.executable_path or "")
    except Exception as exc:  # noqa: BLE001 - no driver, no browser, no PDF
        logger.info("No browser for printing: %s", exc)
        return ""


def why_not() -> str:
    """Why this server cannot print a PDF, or empty if it can.

    Said as a sentence rather than a flag, because each reason wants something
    different done about it and the person reading this is the one who would
    have to do it. Checked properly rather than by whether the library
    imports: a server with playwright and no browser would otherwise offer a
    button that fails when it is pressed, which is the thing this exists to
    prevent.
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        return (
            "This server has no browser to print with: playwright is not "
            "installed. Download the web page and print it instead."
        )
    if settings.pdf_chromium_path:
        if Path(settings.pdf_chromium_path).exists():
            return ""
        return (
            f"PDF_CHROMIUM_PATH points at {settings.pdf_chromium_path}, which is "
            "not there."
        )
    found = _playwright_browser()
    if not found or not Path(found).exists():
        return (
            "This server has playwright but no browser for it to drive. Run "
            "`playwright install chromium` on the server, or point "
            "PDF_CHROMIUM_PATH at a chromium that is already there. Until then, "
            "download the web page and print it instead."
        )
    return ""


def available() -> bool:
    return not why_not()


def _bound_together(sheets: list[bytes]) -> bytes:
    """Several printings of one board as one document."""
    if len(sheets) == 1:
        return sheets[0]
    from pypdf import PdfReader, PdfWriter

    document = PdfWriter()
    for sheet in sheets:
        for printed in PdfReader(io.BytesIO(sheet)).pages:
            document.add_page(printed)
    buffer = io.BytesIO()
    document.write(buffer)
    return buffer.getvalue()


def render(html: str, landscape: bool = True) -> bytes:
    """The exported page, printed.

    Landscape by default: a dashboard is a wide thing, and a twelve-column
    board squeezed onto portrait A4 is a column of thumbnails.
    """
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="surveyhq-pdf-") as folder:
        source = Path(folder) / "board.html"
        source.write_text(html, encoding="utf-8")
        with sync_playwright() as driver:
            browser = driver.chromium.launch(
                executable_path=settings.pdf_chromium_path or None,
                # No sandbox because this runs as an unprivileged user in a
                # container that cannot grant one. What it opens is a file
                # this server has just written, with every other request
                # refused below, so there is nothing here to be sandboxed
                # from.
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page(viewport=VIEWPORT)
                page.set_default_timeout(TIMEOUT_MS)
                page.route(
                    "**",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith("file://")
                        else route.abort()
                    ),
                )
                page.goto(source.as_uri(), wait_until="load")
                page.wait_for_function("document.documentElement.dataset.drawn")

                tabs = page.locator(".tabs button")
                pages = max(1, tabs.count())
                sheets: list[bytes] = []
                for index in range(pages):
                    if pages > 1:
                        drawn = page.evaluate("document.documentElement.dataset.drawn")
                        tabs.nth(index).click()
                        page.wait_for_function(
                            "was => document.documentElement.dataset.drawn !== was",
                            arg=drawn,
                        )
                    # The page opens its folded groups and measures its charts
                    # for paper in its own print handlers, which a browser
                    # printing by itself does not fire.
                    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
                    page.wait_for_timeout(200)
                    sheets.append(
                        page.pdf(
                            format="A4",
                            landscape=landscape,
                            print_background=True,
                            # The page's own @page rule carries the margins,
                            # and it is the one a person printing this file
                            # gets, so it is the one this follows.
                            prefer_css_page_size=True,
                        )
                    )
                    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
                return _bound_together(sheets)
            finally:
                browser.close()
