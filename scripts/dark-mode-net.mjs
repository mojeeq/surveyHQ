/**
 * Fails if something drawn for white paper would show through on a dark page.
 *
 * The ink palette is the light one, so an element naming an ink colour and
 * nothing else keeps it when the theme goes dark. index.css carries a rule
 * per shade under `.dark` to catch what was not thought about: the text
 * shades were added when the Overview's headline numbers came out near-black
 * on near-black, and the borders, dividers and surfaces when a sweep of the
 * running app measured a #edecec hairline under every row of the dataset list
 * and an #e8e8e8 box around every panel on Explore.
 *
 * Two things are checked here. That the net is still in the stylesheet, since
 * deleting a rule puts forty class attributes back on the light palette and
 * nothing else would say so. And `bg-white`, which the net cannot cover: a
 * preview of a white dashboard wants white in dark mode, so each one has to
 * pair itself by hand.
 *
 * Run from `prelint`, so CI catches a new one.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('../frontend/src', import.meta.url))
const CSS = readFileSync(join(SRC, 'index.css'), 'utf8')

const NET = [
  ['text', /\.dark \.text-ink-900 \{/],
  ['borders', /\.dark \.border-ink-100,\s*\n\s*\.dark \.border-ink-200 \{/],
  ['input borders', /\.dark \.border-ink-300 \{/],
  ['dividers', /\.dark \.divide-ink-100 > :not\(\[hidden\]\) ~ :not\(\[hidden\]\)/],
  ['surfaces', /\.dark \.bg-ink-50 \{/],
  // A white tile on a dark board stays drawn for white paper.
  ['the light opt-out', /\.dark \.on-light \.border-ink-100,/],
]

/**
 * Files whose white is the subject rather than the surface: a swatch
 * previewing a light dashboard, the well of a native colour input, and the
 * knob of a switch, which is white in both modes by design.
 */
const WHITE_BY_DESIGN = [
  /components\/DashboardAppearance\.tsx$/,
  /components\/ColorPicker\.tsx$/,
  /components\/ui\/index\.tsx$/,
]

const files = []
const walk = (dir) => {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) walk(path)
    else if (/\.tsx$/.test(path)) files.push(path)
  }
}
walk(SRC)

const missing = NET.filter(([, rule]) => !rule.test(CSS)).map(([what]) => what)
const unpaired = []
for (const path of files) {
  if (WHITE_BY_DESIGN.some((rule) => rule.test(path))) continue
  const text = readFileSync(path, 'utf8')
  const lines = text.split('\n')
  lines.forEach((line, i) => {
    for (const [attribute] of line.matchAll(/className=\{?[`"'][^`"']*[`"']/g)) {
      if (!/\bbg-white\b/.test(attribute) || /dark:bg-/.test(attribute)) continue
      unpaired.push(`${path.slice(SRC.length + 1)}:${i + 1}  ${attribute.slice(0, 80)}`)
    }
  })
}

if (missing.length || unpaired.length) {
  if (missing.length) {
    console.error(`\nindex.css no longer covers: ${missing.join(', ')}.`)
    console.error('Each is one rule under .dark, beside the text shades.\n')
  }
  if (unpaired.length) {
    console.error('\nA white surface with nothing said about dark mode:\n')
    for (const hit of unpaired) console.error('  ' + hit)
    console.error('\n  Pair it: bg-white dark:bg-dark-50\n')
  }
  process.exit(1)
}
console.log(`dark mode: net intact, ${files.length} components checked`)
