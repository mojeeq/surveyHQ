#!/usr/bin/env python3
"""Build the SurveyHQ user manual as a Word document.

The manual is made from the Markdown guides in docs/, so it always says the same
thing as the in-app Help:

- docs/user-guide.md gives the chapters
- docs/survey-solutions.md is Appendix A
- docs/gis-manual.md is Appendix B

Edit those files, not this script, to change what the manual says. Run this
again after editing them.

python-docx is only needed to build the manual, so it isn't in
requirements.txt.

    pip install python-docx
    python scripts/build_manual.py
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
except ImportError:  # pragma: no cover - a build-time dependency
    sys.exit("This needs python-docx: pip install python-docx")

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "SurveyHQ-user-manual.docx"

GUIDE = DOCS / "user-guide.md"
APPENDICES = [
    ("Appendix A", DOCS / "survey-solutions.md"),
    ("Appendix B", DOCS / "gis-manual.md"),
]
# Sections that only make sense on screen: a list of links, or links to files.
SKIP_SECTIONS = {"Contents", "See also"}

INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x6B, 0x6B, 0x6B)
BRAND = RGBColor(0x1D, 0x4E, 0xD8)
CODE_FILL = "F3F4F6"


# --- Styles and small helpers ----------------------------------------------


def style(document: Document) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.15
    for name, size, colour, before in (
        ("Heading 1", 20, BRAND, 22),
        ("Heading 2", 14, INK, 16),
        ("Heading 3", 11.5, INK, 12),
        ("Heading 4", 10.5, INK, 10),
    ):
        heading = document.styles[name]
        heading.font.name = "Calibri"
        heading.font.size = Pt(size)
        heading.font.color.rgb = colour
        heading.font.bold = True
        heading.font.italic = False
        heading.paragraph_format.space_before = Pt(before)
        heading.paragraph_format.space_after = Pt(5)
        heading.paragraph_format.keep_with_next = True


INLINE = re.compile(
    r"(\*\*.+?\*\*"  # bold
    r"|``.+?``"  # code holding a backtick
    r"|`[^`]+`"  # code
    r"|\[[^\]]+\]\([^)]+\)"  # link
    r"|(?<![\w*])\*[^*\s][^*]*?\*(?![\w*]))"  # italic
)


def rich(paragraph, text: str, bold: bool = False, italic: bool = False) -> None:
    """Write Markdown inline text: **bold**, *italic*, `code` and [links](...)."""
    for piece in INLINE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            rich(paragraph, piece[2:-2], bold=True, italic=italic)
        elif piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
            inner = piece.strip("`").strip() if piece.startswith("``") else piece[1:-1]
            run = paragraph.add_run(inner)
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
            run.bold = bold
        elif piece.startswith("[") and "](" in piece and piece.endswith(")"):
            # Links point at other files or headings, which mean nothing on
            # paper, so only the words are kept.
            rich(paragraph, piece[1 : piece.index("](")], bold=bold, italic=italic)
        elif piece.startswith("*") and piece.endswith("*") and len(piece) > 2:
            rich(paragraph, piece[1:-1], bold=bold, italic=True)
        else:
            run = paragraph.add_run(piece)
            run.bold = bold
            run.italic = italic


def para(document: Document, text: str = "", style_name: str | None = None):
    paragraph = document.add_paragraph(style=style_name)
    rich(paragraph, text)
    return paragraph


def bullet(document: Document, text: str) -> None:
    para(document, text, "List Bullet")


def numbered(document: Document, number: str, text: str) -> None:
    # Word's "List Number" style carries one count through the whole document,
    # so each list after the first would start where the last one ended. The
    # number from the source is written out instead.
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.3)
    paragraph.paragraph_format.first_line_indent = Inches(-0.25)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.add_run(f"{number}. ")
    rich(paragraph, text)


def note(document: Document, text: str) -> None:
    """A quoted passage, indented and grey."""
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.25)
    paragraph.paragraph_format.space_before = Pt(4)
    rich(paragraph, text)
    for run in paragraph.runs:
        run.font.size = Pt(10)
        run.font.color.rgb = MUTED


def code(document: Document, lines: list[str]) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.2)
    paragraph.paragraph_format.space_before = Pt(2)
    paragraph.paragraph_format.space_after = Pt(9)
    paragraph.paragraph_format.line_spacing = 1.0
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), CODE_FILL)
    paragraph._p.get_or_add_pPr().append(shading)
    for index, line in enumerate(lines):
        run = paragraph.add_run(line)
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)
        if index < len(lines) - 1:
            run.add_break()


def table(document: Document, headings: list[str], rows: list[list[str]]) -> None:
    grid = document.add_table(rows=1, cols=len(headings))
    grid.style = "Light Grid Accent 1"
    for cell, heading in zip(grid.rows[0].cells, headings, strict=False):
        cell.text = ""
        rich(cell.paragraphs[0], heading, bold=True)
        for run in cell.paragraphs[0].runs:
            run.font.size = Pt(9.5)
    for row in rows:
        cells = grid.add_row().cells
        for cell, value in zip(cells, row, strict=False):
            cell.text = ""
            rich(cell.paragraphs[0], value)
            for run in cell.paragraphs[0].runs:
                run.font.size = Pt(9.5)
    document.add_paragraph().paragraph_format.space_after = Pt(6)


def page_break(document: Document) -> None:
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def footer(document: Document) -> None:
    """Page numbers in the footer."""
    for section in document.sections:
        paragraph = section.footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run("SurveyHQ user manual    ")
        run.font.size = Pt(8)
        run.font.color.rgb = MUTED
        field = paragraph.add_run()
        field.font.size = Pt(8)
        field.font.color.rgb = MUTED
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instruction = OxmlElement("w:instrText")
        instruction.set(qn("xml:space"), "preserve")
        instruction.text = "PAGE"
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        field._r.append(begin)
        field._r.append(instruction)
        field._r.append(end)


# --- Markdown ----------------------------------------------------------------

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^[-*]\s+(.*)$")
NUMBER = re.compile(r"^(\d+)\.\s+(.*)$")


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def sections(text: str) -> list[tuple[int, str, list[str]]]:
    """Split Markdown into (heading level, heading, body lines)."""
    found: list[tuple[int, str, list[str]]] = [(0, "", [])]
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        match = None if fenced else HEADING.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2), []))
        else:
            found[-1][2].append(line)
    return found


def render(document: Document, lines: list[str]) -> None:
    """Write one section's Markdown body (no headings) into the document."""
    text: list[str] = []
    item: tuple[str, str, list[str]] | None = None  # kind, number, lines
    i = 0

    def flush() -> None:
        nonlocal item
        if text:
            para(document, " ".join(text))
            text.clear()
        if item:
            kind, number, words = item
            body = " ".join(words)
            if kind == "bullet":
                bullet(document, body)
            else:
                numbered(document, number, body)
            item = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush()
            i += 1
            continue

        if stripped.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            code(document, block)
            i += 1
            continue

        # An indented block on its own is code, as in a do-file example.
        if line.startswith("    ") and not text and item is None:
            block = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                block.append(lines[i][4:])
                i += 1
            while block and not block[-1].strip():
                block.pop()
            code(document, block)
            continue

        if item and line.startswith(" "):
            item[2].append(stripped)
            i += 1
            continue

        if stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            body = [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            table(document, rows[0], body)
            continue

        if stripped.startswith(">"):
            flush()
            quoted = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quoted.append(lines[i].strip()[1:].strip())
                i += 1
            note(document, " ".join(quoted))
            continue

        if re.fullmatch(r"-{3,}", stripped):
            flush()
            i += 1
            continue

        bullet_match = BULLET.match(line)
        number_match = NUMBER.match(line)
        if bullet_match or number_match:
            flush()
            if bullet_match:
                item = ("bullet", "", [bullet_match.group(1)])
            else:
                item = ("number", number_match.group(1), [number_match.group(2)])
            i += 1
            continue

        if item:
            # A line that isn't indented still belongs to the item it follows.
            item[2].append(stripped)
        else:
            text.append(stripped)
        i += 1
    flush()


def write_markdown(
    document: Document, path: Path, top: int, title_prefix: str | None = None
) -> None:
    """Write a guide, with heading level `top` becoming Heading 1.

    The user guide's ## sections become numbered chapters. For an appendix, its
    # title becomes the appendix heading and everything else moves down a level.
    """
    chapter = 0
    skipping_below: int | None = None
    for level, heading, body in sections(path.read_text(encoding="utf-8")):
        if skipping_below is not None:
            if level and level <= skipping_below:
                skipping_below = None
            else:
                continue
        if heading in SKIP_SECTIONS:
            skipping_below = level
            continue
        if level and level < top:
            continue  # the guide's own title, which the cover already gives
        if level:
            depth = min(level - top + 1, 4)
            if depth == 1:
                page_break(document)
                if title_prefix:
                    heading = f"{title_prefix}. {heading}"
                else:
                    chapter += 1
                    heading = f"{chapter}. {heading}"
            document.add_heading(heading, level=depth)
        render(document, body)


def chapters(path: Path) -> list[str]:
    return [h for level, h, _ in sections(path.read_text(encoding="utf-8")) if level == 2]


def title(path: Path) -> str:
    return next(h for level, h, _ in sections(path.read_text(encoding="utf-8")) if level == 1)


# --- The document --------------------------------------------------------------


def cover(document: Document) -> None:
    for _ in range(6):
        document.add_paragraph()
    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run("SurveyHQ")
    run.font.size = Pt(46)
    run.font.bold = True
    run.font.color.rgb = BRAND

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("User manual")
    run.font.size = Pt(20)
    run.font.color.rgb = INK

    blurb = document.add_paragraph()
    blurb.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = blurb.add_run(
        "Importing survey data, analysis, dashboards,\nindicators, data quality checks and maps"
    )
    run.font.size = Pt(11.5)
    run.font.color.rgb = MUTED

    for _ in range(10):
        document.add_paragraph()
    stamp = document.add_paragraph()
    stamp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = stamp.add_run(dt.date.today().strftime("%d %B %Y"))
    run.font.size = Pt(10)
    run.font.color.rgb = MUTED
    page_break(document)


def contents(document: Document) -> None:
    document.add_heading("Contents", level=1)
    line = document.add_paragraph()
    line.paragraph_format.space_after = Pt(2)
    line.add_run("About this manual").font.size = Pt(10.5)
    for number, name in enumerate(chapters(GUIDE), start=1):
        line = document.add_paragraph()
        line.paragraph_format.space_after = Pt(2)
        line.add_run(f"{number}.  {name}").font.size = Pt(10.5)
    for prefix, path in APPENDICES:
        line = document.add_paragraph()
        line.paragraph_format.space_after = Pt(2)
        line.add_run(f"{prefix}.  {title(path)}").font.size = Pt(10.5)


def about(document: Document) -> None:
    page_break(document)
    document.add_heading("About this manual", level=1)
    para(
        document,
        "SurveyHQ is a web platform for monitoring survey fieldwork. It imports "
        "data from Survey Solutions or from uploaded files, and lets you analyse "
        "it, build dashboards, track indicators against targets and run data "
        "quality checks.",
    )
    para(document, "This manual explains how to use it. It has two appendices:")
    bullet(document, "**Appendix A** explains how to connect to a Survey Solutions server.")
    bullet(document, "**Appendix B** explains how to use boundary files and maps.")
    para(
        document,
        "The same text is available in the app under **Help**. Installation, "
        "backups, upgrades and the API are covered in `deployment.md`, "
        "`architecture.md` and `api.md` in the `docs` folder of the source code.",
    )

    document.add_heading("Who uses what", level=2)
    table(
        document,
        ["Role", "Main parts of the app"],
        [
            ["Survey manager", "Dashboards, indicators and alerts"],
            ["Data manager or statistician", "Datasets, scripts, Analyse and data quality"],
            ["Field supervisor", "A shared dashboard link, on a phone or laptop"],
            ["IT administrator", "Administration, connections and projects"],
        ],
    )


def build() -> Path:
    document = Document()
    for section in document.sections:
        section.left_margin = section.right_margin = Inches(1)
        section.top_margin = section.bottom_margin = Inches(0.9)
    style(document)
    footer(document)

    cover(document)
    contents(document)
    about(document)
    write_markdown(document, GUIDE, top=2)
    for prefix, path in APPENDICES:
        write_markdown(document, path, top=1, title_prefix=prefix)

    document.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)")
