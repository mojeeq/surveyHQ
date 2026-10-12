"""A board printed to PDF by the server.

The web page already carries the board and already has a print layout, so a
PDF is that page printed rather than a second layout to keep in step. What
these tests hold to is the part that is this platform's rather than the
browser's: that a server without a browser says so instead of failing
obscurely, that the whole board is printed rather than whichever tab happens
to be in front, and that the file comes back as a PDF named after the board.

The printing itself needs a browser, which a CI leg may not have, so those
tests skip where there is none rather than pretending to pass.
"""

from __future__ import annotations

import io

import pytest

from app.services import export_pdf


def _said(pdf: bytes) -> str:
    """The words in a PDF, as words.

    Decomposed first: the typeface sets "fi" as one glyph, so a document
    saying "the first page" comes back out of the file saying "the ﬁrst
    page" and a test looking for the one would not find the other.
    """
    import unicodedata

    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(pdf)).pages
    joined = " ".join(" ".join((page.extract_text() or "").split()) for page in pages)
    return unicodedata.normalize("NFKD", joined)


needs_a_browser = pytest.mark.skipif(
    not export_pdf.available(), reason=export_pdf.why_not() or "no browser"
)


def test_a_server_with_no_browser_says_what_is_missing(monkeypatch):
    """And says it where somebody can act on it, rather than in a traceback."""
    import builtins

    real = builtins.__import__

    def without_playwright(name, *rest, **named):
        if name.startswith("playwright"):
            raise ImportError("no playwright here")
        return real(name, *rest, **named)

    monkeypatch.setattr(builtins, "__import__", without_playwright)

    reason = export_pdf.why_not()
    assert "playwright is not installed" in reason
    assert "print it instead" in reason, "and what to do about it"
    assert not export_pdf.available()


def test_a_browser_that_is_not_where_it_says_is_reported(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "pdf_chromium_path", "/nowhere/chrome")
    assert "/nowhere/chrome" in export_pdf.why_not()


def test_playwright_without_a_browser_is_not_a_server_that_can_print(monkeypatch):
    """The case the flag exists for: the library installed and no browser.

    Reported as something to do rather than as a button that fails when it is
    pressed, which is what this used to be - the check asked only whether the
    library imported.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "pdf_chromium_path", "")
    monkeypatch.setattr(export_pdf, "_playwright_browser", lambda: "")

    reason = export_pdf.why_not()
    assert "no browser for it to drive" in reason
    assert "playwright install chromium" in reason, "and what to run"
    assert not export_pdf.available()


def test_the_sheets_of_a_board_are_bound_into_one_document():
    """A board of several pages is printed a page at a time and joined up."""
    from pypdf import PdfReader, PdfWriter

    def one_sheet() -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    joined = export_pdf._bound_together([one_sheet(), one_sheet(), one_sheet()])
    assert len(PdfReader(io.BytesIO(joined)).pages) == 3
    # One sheet is handed back as it is rather than copied through pypdf.
    single = one_sheet()
    assert export_pdf._bound_together([single]) is single


@needs_a_browser
def test_a_board_prints_as_the_board(client, auth_headers):
    """End to end: a real export, printed, with the figures still in it."""
    import pandas as pd
    from pypdf import PdfReader

    from tests.test_api_analytics import _stata_bytes, _zip_bytes

    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(12)],
            "province": ["Shefa"] * 7 + ["Sanma"] * 5,
        }
    )
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("printed.zip", _zip_bytes({"printed.dta": _stata_bytes(frame)}),
                        "application/zip")},
    )
    dataset_id = uploaded.json()["datasets"][0]["id"]
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Printed board"}
    ).json()
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "By province",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {"query": {"dimensions": [{"variable": "province"}],
                               "measures": [{"agg": "count"}]}},
        },
    ).json()
    client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "By province", "widget_type": "chart", "chart_id": chart["id"]},
    )

    printed = client.get(
        f"/api/v1/dashboards/{board['id']}/export.pdf", headers=auth_headers
    )
    assert printed.status_code == 200, printed.text
    assert printed.headers["content-type"] == "application/pdf"
    assert printed.headers["content-disposition"].endswith('printed-board.pdf"')

    pages = PdfReader(io.BytesIO(printed.content)).pages
    text = _said(printed.content)
    assert "Printed board" in text
    assert "By province" in text
    # Landscape A4: a dashboard is a wide thing.
    assert float(pages[0].mediabox.width) > float(pages[0].mediabox.height)


@needs_a_browser
def test_every_page_of_a_board_is_printed(client, auth_headers):
    """Only the tab in front is in the document, so each is printed in turn."""

    board = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "Two pages"},
    ).json()
    client.patch(
        f"/api/v1/dashboards/{board['id']}",
        headers=auth_headers,
        json={"pages": [{"name": "Home Page"}, {"name": "Fieldwork"}]},
    )
    for page, content in ((0, "the first page"), (1, "the second page")):
        client.post(
            f"/api/v1/dashboards/{board['id']}/widgets",
            headers=auth_headers,
            json={"title": f"Note {page}", "widget_type": "text", "page": page,
                  "config": {"content": content}},
        )

    printed = client.get(
        f"/api/v1/dashboards/{board['id']}/export.pdf", headers=auth_headers
    )
    assert printed.status_code == 200, printed.text
    text = _said(printed.content)
    assert "the first page" in text
    assert "the second page" in text, "the tab nobody was looking at"


def test_the_interface_is_told_whether_this_server_can_print(client, auth_headers):
    info = client.get("/api/v1/system/info", headers=auth_headers)
    assert info.status_code == 200, info.text
    body = info.json()
    assert body["pdf_export"] is export_pdf.available()
    assert bool(body["pdf_export_reason"]) is not body["pdf_export"]
