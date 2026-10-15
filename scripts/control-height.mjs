/**
 * Fails if a second stylesheet decides how tall a control is.
 *
 * The platform showed three button heights in a single header: 38 from
 * index.css, 36 from redesign.css, which loads second and quietly won, and 32
 * from a `.btn-sm` the two sheets disagreed about. None of the three was
 * chosen. Each was whatever a line box worked out to, in whichever sheet
 * happened to load last, and fields stood 40 tall beside all of them.
 *
 * The symptom had already been patched once without being found. There is a
 * comment in redesign.css explaining that `.btn-sm` ended up four pixels
 * taller than `.input-sm`, so the dashboard's filter bar grew from 42 to 46
 * pixels the moment a Clear button appeared and nudged every widget down. The
 * fix was a fourth size class, `.btn-xs`.
 *
 * So the heights are declared now, as --control-height and its two smaller
 * steps, and only index.css may say what they are. This holds the other
 * sheets to that, because the next person to add a size class in the second
 * one will not see any of the above.
 *
 * The markup is read too, because a stylesheet is not the only place a height
 * can be set. The sign-in button carried `h-9` and stood 36 tall above two
 * 32-tall fields, on the first screen anyone sees, and no amount of declaring
 * in CSS would have reached it: a `min-height` is a floor, and a utility on
 * the element clears it.
 *
 * Run from `prelint`, so CI catches a new one. Not a vitest guard: vitest
 * returns an empty module for a CSS import, `?raw` included.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('../frontend/src', import.meta.url))
const read = (name) => readFileSync(join(SRC, name), 'utf8')

const INDEX = read('index.css')
/** Every sheet loaded after index.css, which is every sheet that can win. */
const LATER = ['redesign.css', 'aero.css']

const STEPS = ['--control-height', '--control-height-sm', '--control-height-xs']

/** Rules naming a control, with the declarations inside them. */
function controlRules(css) {
  const out = []
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = match[1].trim()
    if (!/\.(btn|input|icon-button)\b/.test(selector)) continue
    out.push({ selector, body: match[2] })
  }
  return out
}

/** A height set as a measurement rather than against the shared step. */
function literalHeight(body) {
  const found = []
  for (const line of body.split(';')) {
    const utility = line.match(/\b(min-h|h)-(\d+(\.\d+)?|px|\[[^\]]+\])/)
    if (utility) found.push(utility[0])
    const declared = line.match(/(?:^|\s)(min-height|height)\s*:\s*([^;]+)/)
    if (declared && !/var\(--control-height/.test(declared[2]) && !/auto/.test(declared[2])) {
      found.push(`${declared[1]}: ${declared[2].trim()}`)
    }
  }
  return found
}

const problems = []

// The steps themselves, named once and in the sheet that owns them.
for (const step of STEPS) {
  if (!new RegExp(`${step}:\\s*\\d+px`).test(INDEX)) {
    problems.push(`index.css no longer declares ${step}.`)
  }
}

// Two heights three pixels apart read as a mistake rather than a choice,
// which is how this started.
const px = (step) => Number(new RegExp(`${step}:\\s*(\\d+)px`).exec(INDEX)?.[1])
const [tall, short, tiny] = STEPS.map(px)
if (!(tall > short && short > tiny)) {
  problems.push(`The steps are ${tall}, ${short}, ${tiny}px, which is not a descending set.`)
} else if (tall - short < 3 || short - tiny < 3) {
  problems.push(
    `The steps are ${tall}, ${short}, ${tiny}px. A gap under three pixels is the ` +
      'near miss this replaced, not a size somebody picked.',
  )
}

// Geometry in a sheet that loads later than the one owning it.
for (const sheet of LATER) {
  for (const rule of controlRules(read(sheet))) {
    const heights = literalHeight(rule.body)
    if (heights.length) {
      problems.push(`${sheet}: ${rule.selector} sets ${heights.join(', ')}`)
    }
  }
}

// The filter bar case: a button and the field beside it stand in one row, and
// the taller one sets the row's height and shifts the dashboard when it
// appears. They are the same height only while both read the same step.
const compact = read('redesign.css')
for (const [selector, pattern] of [
  ['.btn-xs', /\.btn-xs\s*\{([^}]*)\}/],
  ['.input.input-sm', /\.input\.input-sm\s*\{([^}]*)\}/],
]) {
  const body = pattern.exec(compact)?.[1] ?? ''
  if (!/var\(--control-height-sm\)/.test(body)) {
    problems.push(`${selector} no longer stands at --control-height-sm.`)
  }
}

// A height written onto the element instead, which no amount of declaring in
// a stylesheet can reach.
const CONTROL_CLASS = /\b(btn|btn-primary|btn-secondary|btn-danger|btn-ghost|btn-sm|btn-xs|input|icon-button)\b/
const HEIGHT_UTILITY = /\b(min-h|h)-(\d+(\.\d+)?|px|full|\[[^\]]+\])/

/**
 * The two controls that are meant to be taller than a row: a box typed into
 * over several lines, and a list box showing its options at once. Both are
 * several rows by definition, so a row's height is the wrong thing to hold
 * them to.
 */

/** The tag an attribute belongs to, found by walking back to its opening. */
function openingTag(text, at) {
  const start = text.lastIndexOf('<', at)
  if (start < 0) return { name: '', attributes: '' }
  const name = /^<([a-zA-Z][\w.]*)/.exec(text.slice(start, start + 24))?.[1] ?? ''
  // Far enough to carry the rest of one element's attributes and no further.
  return { name, attributes: text.slice(start, start + 400) }
}

const grows = (text, at) => {
  const { name, attributes } = openingTag(text, at)
  if (name === 'textarea') return true
  return name === 'select' && /\bmultiple\b/.test(attributes)
}

const components = []
const walk = (dir) => {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) walk(path)
    else if (/\.tsx$/.test(path)) components.push(path)
  }
}
walk(SRC)

for (const path of components) {
  const text = readFileSync(path, 'utf8')
  for (const match of text.matchAll(/className=\{?[`"'][^`"']*[`"']/g)) {
    const attribute = match[0]
    if (!CONTROL_CLASS.test(attribute) || !HEIGHT_UTILITY.test(attribute)) continue
    if (grows(text, match.index)) continue
    const line = text.slice(0, match.index).split('\n').length
    problems.push(`${path.slice(SRC.length + 1)}:${line}  ${attribute.slice(0, 72)}`)
  }
}

if (problems.length) {
  console.error('\nA control height is set somewhere other than index.css:\n')
  for (const problem of problems) console.error('  ' + problem)
  console.error(
    '\n  Heights belong to index.css, against --control-height and its smaller\n' +
      '  steps. Two stylesheets with an opinion about the same geometry is not a\n' +
      '  style, it is a race, and the header grows three button sizes. A height\n' +
      '  on the element itself clears the declared one just as thoroughly: drop\n' +
      '  the utility, or add a step if the size is one the platform needs.\n' +
      '  A textarea and a list box are already free to grow.\n',
  )
  process.exit(1)
}
console.log(
  `control height: one owner, steps ${tall}/${short}/${tiny}px, ` +
    `${components.length} components checked`,
)
