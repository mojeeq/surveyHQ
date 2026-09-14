#!/usr/bin/env node
/**
 * Turns docs/*.md into the help the platform serves at /help.
 *
 * The point of doing it this way is that there is exactly one copy of the
 * documentation. A Help page written by hand would be a second copy, and a
 * second copy of anything is a copy that is wrong by the next release - which
 * is worse than no help page at all, because somebody trusts it.
 *
 * So the markdown in docs/ is the source and this renders it at build time.
 * The output is generated rather than committed: it is rebuilt by npm run dev,
 * npm run build and npm run lint through their pre- hooks, so it cannot go
 * stale, and no generated file turns up in a review diff.
 *
 *     node scripts/build-help.mjs
 *
 * Rendering happens here rather than in the browser so the application carries
 * no markdown parser: the page ships HTML it can print directly. The subset
 * below is the subset docs/ actually uses, checked rather than assumed.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const DOCS = join(ROOT, "docs");
const OUT = join(ROOT, "frontend", "src", "help", "content.generated.ts");

/**
 * What the Help page offers, in the order it offers it.
 *
 * Every document, to everybody. The deployment and architecture notes were at
 * one point kept back from all but an administrator, on the grounds that a
 * viewer looking for how to read a dashboard should not have to walk past TLS
 * certificates to find it. That was solving the wrong problem: none of it is
 * secret, all of it is in the public repository, and an analyst who wants to
 * know how the platform stores a dataset should be able to read how. Putting
 * the everyday documents first is what the ordering is for.
 */
const MANIFEST = [
  {
    id: "user-guide",
    file: "user-guide.md",
    title: "User guide",
    summary: "Projects, importing data, analysing, dashboards and monitoring.",
  },
  {
    id: "gis",
    file: "gis-manual.md",
    title: "Boundaries and maps",
    summary:
      "The enumeration-area frame, and checking a record was collected where it says.",
  },
  {
    id: "survey-solutions",
    file: "survey-solutions.md",
    title: "Survey Solutions",
    summary: "Connecting a server, importing, scheduling, and the errors it gives.",
  },
  {
    id: "api",
    file: "api.md",
    title: "API reference",
    summary: "Every endpoint, with examples, for scripting against the platform.",
  },
  {
    id: "deployment",
    file: "deployment.md",
    title: "Deployment",
    summary: "Installing, TLS, backups, upgrades and troubleshooting the server.",
  },
  {
    id: "architecture",
    file: "architecture.md",
    title: "How it works",
    summary: "The pieces the platform is built from, and why they were chosen.",
  },
];

// --- escaping ---------------------------------------------------------------

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const escape = (text) => String(text).replace(/[&<>"']/g, (c) => ESCAPES[c]);

// Code spans are lifted out before the rest of the inline rules run and put
// back after, so a ** inside backticks stays two asterisks rather than
// becoming bold. The placeholder is deliberately something no document
// contains rather than a control character, which survives copy and paste.
const HOLE = (index) => "@@codespan" + index + "@@";

function inline(raw) {
  const spans = [];
  let text = escape(raw).replace(/`([^`]+)`/g, (_, code) => {
    spans.push(code);
    return HOLE(spans.length - 1);
  });

  text = text
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => link(label, href))
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");

  return text.replace(/@@codespan(\d+)@@/g, (_, index) => {
    return "<code>" + spans[Number(index)] + "</code>";
  });
}

/**
 * The same text with its markup taken off, for the search index.
 *
 * Search reads the source line rather than the rendered HTML, which is right -
 * tags would match - but the source still carries the markers. Leaving them in
 * put "**Boundaries**" and backticks into the snippets the reader is shown.
 */
function plain(raw) {
  return raw
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)\s]+\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1$2")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * A link, rewritten for a page that lives inside the application.
 *
 * A cross-reference between two documents is a relative filename on disk, and
 * here it has to become the route for that document or it is a dead link. One
 * naming a document the Help page does not carry is left as plain text:
 * better a phrase than a link that goes nowhere.
 */
function link(label, href) {
  if (/^https?:\/\//.test(href)) {
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  }
  if (href.startsWith("#")) return `<a href="${href}">${label}</a>`;
  const [file, anchor] = href.split("#");
  const doc = MANIFEST.find((entry) => entry.file === file.replace(/^\.?\//, ""));
  if (!doc) return label;
  return `<a href="/help/${doc.id}${anchor ? "#" + anchor : ""}">${label}</a>`;
}

/** GitHub's heading anchors, so a link written for the repo works here too. */
function slugify(heading, seen) {
  const base =
    heading
      .toLowerCase()
      .replace(/`/g, "")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-") || "section";
  const count = seen.get(base) ?? 0;
  seen.set(base, count + 1);
  return count ? `${base}-${count}` : base;
}

/** A table row split on pipes, tolerating the optional outer ones. */
const cells = (line) =>
  line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((cell) => cell.trim());

const isDivider = (line) =>
  /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes("-");

// --- the renderer -----------------------------------------------------------

function render(markdown) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  const headings = [];
  const seen = new Map();
  const sections = [];
  // Plain text kept per section, for search. A hit has to be able to say which
  // heading it was under, so text accumulates against the most recent one.
  let section = { id: "", title: "", text: [] };

  const closeSection = () => {
    if (section.title) sections.push({ ...section, text: section.text.join(" ") });
  };

  let at = 0;
  let paragraph = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const text = paragraph.join(" ");
    html.push(`<p>${inline(text)}</p>`);
    section.text.push(plain(text));
    paragraph = [];
  };

  while (at < lines.length) {
    const line = lines[at];

    // Fenced code, taken verbatim including any markdown inside it.
    if (/^\s*```/.test(line)) {
      flushParagraph();
      const language = line.replace(/^\s*```/, "").trim();
      const body = [];
      at += 1;
      while (at < lines.length && !/^\s*```/.test(lines[at])) {
        body.push(lines[at]);
        at += 1;
      }
      at += 1;
      const cls = language ? ` class="lang-${escape(language)}"` : "";
      html.push(`<pre${cls}><code>${escape(body.join("\n"))}</code></pre>`);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      at += 1;
      continue;
    }

    // Rules first, so --- is not mistaken for anything else.
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushParagraph();
      html.push("<hr>");
      at += 1;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      const title = heading[2].trim().replace(/\s*#+\s*$/, "");
      const id = slugify(title, seen);
      // The first heading is the document's own title, which the page prints
      // from the manifest, so it is not repeated in the body or the outline.
      if (level === 1 && !headings.length && !html.length) {
        at += 1;
        continue;
      }
      if (level <= 3) {
        closeSection();
        section = { id, title, text: [] };
        headings.push({ id, title, level });
      }
      html.push(`<h${level} id="${id}">${inline(title)}</h${level}>`);
      at += 1;
      continue;
    }

    // Blockquote, one level, which is all the docs use.
    if (/^\s*>\s?/.test(line)) {
      flushParagraph();
      const body = [];
      while (at < lines.length && /^\s*>\s?/.test(lines[at])) {
        body.push(lines[at].replace(/^\s*>\s?/, ""));
        at += 1;
      }
      const text = body.join(" ").trim();
      html.push(`<blockquote><p>${inline(text)}</p></blockquote>`);
      section.text.push(plain(text));
      continue;
    }

    // Pipe table: a header row, a divider, then body rows.
    if (line.includes("|") && at + 1 < lines.length && isDivider(lines[at + 1])) {
      flushParagraph();
      const header = cells(line);
      at += 2;
      const body = [];
      while (at < lines.length && lines[at].includes("|") && lines[at].trim()) {
        body.push(cells(lines[at]));
        at += 1;
      }
      // Several tables in the docs have a blank header row, which is how a
      // two-column layout table is written in markdown. An empty band of
      // column headings above it is noise, so it is dropped.
      const titled = header.some((cell) => cell !== "");
      const head = titled
        ? `<thead><tr>${header.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>`
        : "";
      const rows = body
        .map((row) => `<tr>${row.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`)
        .join("");
      html.push(
        `<div class="doc-table"><table>${head}<tbody>${rows}</tbody></table></div>`,
      );
      section.text.push(plain([...(titled ? header : []), ...body.flat()].join(" ")));
      continue;
    }

    // Lists, one level, which is what the docs use. A wrapped item continues
    // on an indented line.
    const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      const pattern = ordered ? /^\s*\d+[.)]\s+(.*)$/ : /^\s*[-*+]\s+(.*)$/;
      const items = [];
      while (at < lines.length) {
        const item = lines[at].match(pattern);
        if (!item) {
          if (items.length && /^\s+\S/.test(lines[at]) && lines[at].trim()) {
            items[items.length - 1] += " " + lines[at].trim();
            at += 1;
            continue;
          }
          break;
        }
        items.push(item[1].trim());
        at += 1;
      }
      const tag = ordered ? "ol" : "ul";
      html.push(`<${tag}>${items.map((i) => `<li>${inline(i)}</li>`).join("")}</${tag}>`);
      section.text.push(plain(items.join(" ")));
      continue;
    }

    paragraph.push(line.trim());
    at += 1;
  }

  flushParagraph();
  closeSection();
  return { html: html.join("\n"), headings, sections };
}

// --- build ------------------------------------------------------------------

const documents = [];
const missing = [];

for (const entry of MANIFEST) {
  const path = join(DOCS, entry.file);
  if (!existsSync(path)) {
    // Not a failure. A document can arrive in a later release, and a build
    // that refused to run because one was absent would be a build broken by
    // documentation.
    missing.push(entry.file);
    continue;
  }
  const { html, headings, sections } = render(readFileSync(path, "utf8"));
  documents.push({
    id: entry.id,
    title: entry.title,
    summary: entry.summary,
    source: entry.file,
    html,
    headings,
    sections,
  });
}

// One document absent is a documentation state and is tolerated above. All of
// them absent is a broken build: it means docs/ never reached this script, for
// instance because a Docker build context does not include it. Without this
// the build would succeed and ship a Help page with nothing in it, which is
// the worst of the outcomes because nobody finds out until a user looks.
if (documents.length === 0) {
  console.error(
    `help: no documentation was found in ${DOCS}. The build cannot continue, ` +
      "because a Help page with nothing in it would ship without complaint.",
  );
  process.exit(1);
}

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(
  OUT,
  `// Generated by scripts/build-help.mjs from docs/. Do not edit by hand.
// Rebuilt by npm run dev, npm run build and npm run lint.

export interface HelpHeading {
  id: string
  title: string
  level: number
}

export interface HelpSection {
  id: string
  title: string
  text: string
}

export interface HelpDocument {
  id: string
  title: string
  summary: string
  source: string
  html: string
  headings: HelpHeading[]
  sections: HelpSection[]
}

export const HELP_DOCUMENTS: HelpDocument[] = ${JSON.stringify(documents, null, 2)}
`,
  "utf8",
);

const words = documents.reduce(
  (total, doc) =>
    total + doc.sections.reduce((n, s) => n + s.text.split(/\s+/).filter(Boolean).length, 0),
  0,
);
console.log(
  `help: ${documents.length} document(s), ` +
    `${documents.reduce((n, d) => n + d.headings.length, 0)} sections, ` +
    `~${words.toLocaleString()} words` +
    (missing.length ? ` (not present yet: ${missing.join(", ")})` : ""),
);
