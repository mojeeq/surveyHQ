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
 * Run from `prelint`, so CI catches a new one. Not a vitest guard: vitest
 * returns an empty module for a CSS import, `?raw` included.
 */
import { readFileSync } from 'node:fs'
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

if (problems.length) {
  console.error('\nA control height is set somewhere other than index.css:\n')
  for (const problem of problems) console.error('  ' + problem)
  console.error(
    '\n  Heights belong to index.css, against --control-height and its smaller\n' +
      '  steps. Two stylesheets with an opinion about the same geometry is not a\n' +
      '  style, it is a race, and the header grows three button sizes.\n',
  )
  process.exit(1)
}
console.log(`control height: one owner, steps ${tall}/${short}/${tiny}px`)
