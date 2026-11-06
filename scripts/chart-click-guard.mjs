/**
 * Fails if a chart gesture reports a category without the fold guard.
 *
 * A top-N display folds everything past the cut into one invented bar,
 * "Other (5)". It stands for several categories and is not any of them, so
 * filtering by it asks for rows whose value is literally "Other (5)": there
 * are none, every widget on the page empties at once, and nothing says why.
 *
 * ChartCard reports a clicked category through one function, `report`, which
 * drops that bar. The rule is easy to break by adding a second gesture and
 * calling `onSelect` straight from it - which is exactly what happened: the
 * click on a slice was guarded while the click on a pie's legend, the one
 * gesture that actually names a category on a pie, was not.
 *
 * So the rule is checked here rather than remembered. Only inside ChartCard,
 * where `report` exists; every other component calls `onSelect` as its own
 * prop and is none of this script's business.
 *
 * Run from `prelint`, so CI catches the next one.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FILE = fileURLToPath(new URL('../frontend/src/components/ChartCard.tsx', import.meta.url))

const source = readFileSync(FILE, 'utf8')
const lines = source.split('\n')

// Where the handlers live. `onSelect` outside it is the prop being declared,
// destructured or tested for, not a gesture reporting a category.
const start = lines.findIndex((line) => line.includes('onEvents={'))
if (start < 0) {
  console.error('\nChartCard has no onEvents block; this guard needs rewriting.\n')
  process.exit(1)
}

const found = []
for (let i = start; i < lines.length; i += 1) {
  const line = lines[i]
  // A call, not a mention: `onSelect(` with nothing but whitespace or an
  // opening brace before it. `?` and `&&` tests do not match.
  if (/(?<![.\w])onSelect\s*\(/.test(line)) {
    found.push(`${i + 1}  ${line.trim()}`)
  }
}

if (found.length) {
  console.error('\nA chart gesture reports a category without the fold guard:\n')
  for (const hit of found) console.error('  ChartCard.tsx:' + hit)
  console.error('\n  Call report(category) instead of onSelect(category).')
  console.error('  It drops the "Other (N)" bar a top-N display invents, which')
  console.error('  no row carries and which empties every widget when filtered on.\n')
  process.exit(1)
}

// And the guard itself has to still be the thing `report` applies.
if (!/const report = \([\s\S]{0,200}isFoldedBar\(result, category\)/.test(source)) {
  console.error('\nChartCard.report no longer applies isFoldedBar; this guard needs rewriting.\n')
  process.exit(1)
}

console.log('chart clicks report through the fold guard')
