"""The front page of a destination that lists what is published there.

Several dashboards on one site each have an address of their own, and without
this the site's own address - the one people are actually told - is a 404 on
GitHub Pages and a directory listing or nothing on most servers. One page
listing them, rewritten whenever one is published or taken down, is the link
that can go into a report.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from html import escape

from app.services.publishing.sites import MARKER


@dataclass
class Entry:
    name: str
    description: str
    path: str
    updated: dt.datetime | None


def _when(moment: dt.datetime | None) -> str:
    return moment.strftime("%d %B %Y").lstrip("0") if moment else ""


def render(title: str, entries: list[Entry]) -> bytes:
    """The page, as bytes ready to upload."""
    items = "\n".join(
        f"""      <li>
        <a href="./{escape(entry.path, quote=True)}/">{escape(entry.name)}</a>
        {f'<p>{escape(entry.description)}</p>' if entry.description else ''}
        {f'<small>Updated {escape(_when(entry.updated))}</small>' if entry.updated else ''}
      </li>"""
        for entry in sorted(entries, key=lambda one: one.name.lower())
    )
    body = items or "      <li class=\"none\">Nothing is published here yet.</li>"
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{MARKER}
<title>{escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; --ink: #1c1b19; --soft: #6f6c66; --line: #e3e1dc;
          --canvas: #f4f3f1; --card: #ffffff; --link: #2f6fd0; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink: #ecebe8; --soft: #a3a09a; --line: #34332f; --canvas: #161513;
            --card: #1f1e1b; --link: #7aa7ec; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--canvas); color: var(--ink);
         font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 40px 16px 64px; }}
  h1 {{ font-size: 24px; margin: 0 0 20px; }}
  ul {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }}
  li {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px;
       padding: 14px 16px; }}
  li a {{ color: var(--link); font-weight: 600; font-size: 16px; text-decoration: none; }}
  li a:hover {{ text-decoration: underline; }}
  li p {{ margin: 4px 0 0; }}
  li small {{ display: block; margin-top: 6px; color: var(--soft); }}
  li.none {{ color: var(--soft); }}
</style>
</head>
<body>
  <main>
    <h1>{escape(title)}</h1>
    <ul>
{body}
    </ul>
  </main>
</body>
</html>
"""
    return page.encode("utf-8")
