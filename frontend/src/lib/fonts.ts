/**
 * The typefaces a dashboard can be set in.
 *
 * Two kinds sit in one list. The **bundled** ones are real fonts served by this
 * installation: the files ship with the platform, so a board renders in the
 * face it was designed in on any machine that can reach the server, whatever
 * that machine happens to have installed. The **system** ones name no file at
 * all and fall through a stack of whatever is already there; they cost nothing
 * to download and are the right answer when a ministry wants its boards to
 * look like the rest of its documents.
 *
 * Nothing here is fetched from Google or any other third party. That is
 * deliberate and worth keeping: a font request to an outside host is a record
 * of who is reading which dashboard, sent somewhere this platform does not
 * control, and it is the one thing that would stop a board rendering properly
 * on a ministry network that blocks outside traffic.
 *
 * `@fontsource-variable` packages carry one file per family covering every
 * weight from 100 to 900, and the browser fetches only the character subset a
 * page actually uses. A board in English downloads no Cyrillic.
 */

export type FontKind = "bundled" | "system";

export interface FontChoice {
  /** Stable key stored on a dashboard. Never change one of these in place. */
  id: string;
  label: string;
  /** What goes into `font-family`. Always ends in a generic family. */
  stack: string;
  kind: FontKind;
  /**
   * The bundled family's own name, as its `@font-face` declares it. The export
   * matches on this to decide which files to carry, so it must be exactly the
   * string the font package uses.
   */
  family?: string;
  /** A word on what it is for, shown beside the name in the picker. */
  note: string;
  /**
   * Stacks this font was stored as before the catalogue existed.
   *
   * Widget styling has always kept the CSS stack itself, and the two pickers
   * that preceded this file used different stacks for the same face - the
   * dashboard title list said Georgia with Nimbus Roman in it, the widget list
   * said Georgia without. Both strings are in real dashboards. Listing them
   * here is what lets an existing widget still show its own font selected in
   * the picker rather than appearing to have lost it.
   */
  legacy?: string[];
}

/** Appended to every bundled stack, so a failed font load still lands somewhere. */
const SANS_FALLBACK = 'system-ui, -apple-system, "Segoe UI", sans-serif';
const SERIF_FALLBACK = 'Georgia, "Times New Roman", serif';
const MONO_FALLBACK = 'ui-monospace, Menlo, Consolas, monospace';

export const FONTS: FontChoice[] = [
  {
    id: "",
    label: "Interface",
    stack: "",
    kind: "system",
    note: "Whatever the rest of the platform uses",
  },

  // -- Bundled -------------------------------------------------------------
  {
    id: "inter",
    label: "Inter",
    stack: `"Inter Variable", ${SANS_FALLBACK}`,
    kind: "bundled",
    family: "Inter Variable",
    note: "Neutral and dense; made for screens",
  },
  {
    id: "source-sans",
    label: "Source Sans",
    stack: `"Source Sans 3 Variable", ${SANS_FALLBACK}`,
    kind: "bundled",
    family: "Source Sans 3 Variable",
    note: "Warmer, easy at small sizes",
  },
  {
    id: "plex-sans",
    label: "IBM Plex Sans",
    stack: `"IBM Plex Sans Variable", ${SANS_FALLBACK}`,
    kind: "bundled",
    family: "IBM Plex Sans Variable",
    note: "Institutional; pairs with IBM Plex Serif",
  },
  {
    id: "space-grotesk",
    label: "Space Grotesk",
    stack: `"Space Grotesk Variable", ${SANS_FALLBACK}`,
    kind: "bundled",
    family: "Space Grotesk Variable",
    note: "Geometric, with character. Good for titles",
  },
  {
    id: "source-serif",
    label: "Source Serif",
    stack: `"Source Serif 4 Variable", ${SERIF_FALLBACK}`,
    kind: "bundled",
    family: "Source Serif 4 Variable",
    note: "A report serif; reads well in long headings",
  },
  {
    id: "plex-serif",
    label: "IBM Plex Serif",
    stack: `"IBM Plex Serif", ${SERIF_FALLBACK}`,
    kind: "bundled",
    family: "IBM Plex Serif",
    note: "Slab-ish serif; the sober one",
  },
  {
    id: "jetbrains-mono",
    label: "JetBrains Mono",
    stack: `"JetBrains Mono Variable", ${MONO_FALLBACK}`,
    kind: "bundled",
    family: "JetBrains Mono Variable",
    note: "Fixed width; digits line up in a column",
  },

  // -- System --------------------------------------------------------------
  //
  // Kept because they need no download at all and because a ministry that has
  // standardised on Arial or Georgia wants its boards to match its documents.
  {
    id: "grotesque",
    label: "Helvetica / Arial",
    stack: '"Helvetica Neue", Helvetica, Arial, sans-serif',
    kind: "system",
    note: "On every machine already",
    // The widget list's old "System" entry, which named no face of its own.
    legacy: ['system-ui, -apple-system, "Segoe UI", sans-serif'],
  },
  {
    id: "serif",
    label: "Georgia",
    stack: 'Georgia, "Times New Roman", "Nimbus Roman", serif',
    kind: "system",
    note: "On every machine already",
    legacy: ['Georgia, "Times New Roman", serif'],
  },
  {
    id: "slab",
    label: "Slab",
    stack: '"Rockwell", "Roboto Slab", "DejaVu Serif", Georgia, serif',
    kind: "system",
    note: "Heavy serif, where installed",
    legacy: ['"Roboto Slab", Rockwell, Georgia, serif'],
  },
  {
    id: "condensed",
    label: "Condensed",
    stack: '"Arial Narrow", "Roboto Condensed", sans-serif',
    kind: "system",
    note: "Fits more words across a narrow widget",
  },
  {
    id: "mono",
    label: "System monospace",
    stack: 'ui-monospace, "SFMono-Regular", Menlo, "DejaVu Sans Mono", monospace',
    kind: "system",
    note: "Fixed width, no download",
    legacy: ['ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace'],
  },
];

const BY_ID = new Map(FONTS.map((f) => [f.id, f]));
const BY_STACK = new Map<string, FontChoice>();
for (const font of FONTS) {
  BY_STACK.set(font.stack, font);
  for (const old of font.legacy ?? []) BY_STACK.set(old, font);
}

/** The CSS for a stored id. Empty or unknown means "inherit", not "guess". */
export function fontStack(id?: string): string | undefined {
  return BY_ID.get(id ?? "")?.stack || undefined;
}

/**
 * The font a stored value names, whichever of the two ways it was stored.
 *
 * Widget styling has always kept the CSS stack itself rather than a key, so
 * both forms are in the database and both have to keep working, along with the
 * older spellings listed on each font. Undefined means the stored value matches
 * nothing known; it is still a perfectly good CSS stack and still renders, so
 * callers show it as a choice of its own rather than pretending it is unset.
 */
export function fontFor(stored?: string): FontChoice | undefined {
  if (!stored) return undefined;
  return BY_ID.get(stored) ?? BY_STACK.get(stored);
}

/** Every bundled family name, for the export to match a stack against. */
export const BUNDLED_FAMILIES: string[] = FONTS.filter((f) => f.kind === "bundled").map(
  (f) => f.family as string,
);
