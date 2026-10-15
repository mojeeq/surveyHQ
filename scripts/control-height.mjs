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
 * the element clears it. That half is parsed rather than scanned, for
 * reasons written out above it.
 *
 * Run from `prelint`, so CI catches a new one. Not a vitest guard: vitest
 * returns an empty module for a CSS import, `?raw` included.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
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

/*
 * Parsed rather than scanned, after three tries at reading .tsx as text.
 *
 * Each try was wrong in a way the last one taught: a `//` inside a url
 * blanked the rest of its line; an explanation of what *not* to write failed
 * the build over a sentence; a code example held as a string did the same,
 * which this codebase keeps by the dozen in ProjectScriptHelp. Marking
 * strings fixed that one and bought the worst kind of mistake in exchange -
 * `Cramér's V`, real text in CrosstabTable, opens a string that never
 * closes, and a genuine `className="btn h-9"` after it was waved through.
 * A guard that misses is worse than no guard, because it is trusted.
 *
 * All of it is the same mistake: a quote means one thing in JavaScript, a
 * second in JSX text, and a third inside a template literal, and no amount of
 * care about quotes tells them apart. TypeScript is already a dependency here
 * and knows precisely, so it reads the file and this asks it for the
 * className attributes. Nothing else in a file can be mistaken for one.
 */
const require = createRequire(join(SRC, '..', 'package.json'))
const ts = require('typescript')

/**
 * The two controls meant to be taller than a row: a box typed into over
 * several lines, and a list box showing its options at once. Both are several
 * rows by definition, so a row's height is the wrong thing to hold them to.
 */
function grows(opening) {
  // The attribute's grandparent is the opening tag itself - its parent is the
  // attribute list - so this is handed the tag, not the element around it.
  if (!opening || !opening.tagName) return false
  const tag = opening.tagName.getText()
  if (tag === 'textarea') return true
  return (
    tag === 'select' &&
    opening.attributes.properties.some(
      (one) => ts.isJsxAttribute(one) && one.name.getText() === 'multiple',
    )
  )
}

/**
 * The class names an attribute can put on an element.
 *
 * The literals inside it rather than its source text. A class name can only
 * come from a string, so this is exact where reading the source is not:
 * `className={/* Never add btn h-9 here. *\/ classes}` has that sentence in
 * its text and neither class on the element. Comments are trivia and never a
 * literal, so there is nothing to strip - they simply are not collected.
 *
 * Every shape the platform writes reduces to the same list: a plain string, a
 * conditional with one on each side, a template literal with interpolations,
 * a helper call with the class and the height in separate arguments.
 */
function classesIn(node) {
  const parts = []
  const walk = (one) => {
    if (
      ts.isStringLiteral(one) ||
      ts.isNoSubstitutionTemplateLiteral(one) ||
      one.kind === ts.SyntaxKind.TemplateHead ||
      one.kind === ts.SyntaxKind.TemplateMiddle ||
      one.kind === ts.SyntaxKind.TemplateTail
    ) {
      parts.push(one.text)
    }
    // The key of a class map, which is a class name written as a name rather
    // than as a string: `cx({ btn: enabled, 'h-9': tall })`. Nothing here
    // uses a helper like that yet, and nothing stops the next person adding
    // one - and this is the shape where missing it would be silent, since
    // the quoted half of the pair is collected either way and the match
    // needs both.
    if (
      (ts.isPropertyAssignment(one) || ts.isShorthandPropertyAssignment(one)) &&
      one.name &&
      (ts.isIdentifier(one.name) || ts.isStringLiteral(one.name))
    ) {
      parts.push(one.name.text)
    }
    one.forEachChild(walk)
  }
  walk(node)
  // Deduped: a quoted key is collected twice, once as a literal and once as
  // a name, which changes no match and reads badly in the report.
  return [...new Set(parts)].join(' ')
}

/** Every className in one file, with the line it is on and its element. */
function classNames(source) {
  const found = []
  const walk = (node) => {
    if (ts.isJsxAttribute(node) && node.name.getText() === 'className') {
      found.push({
        text: node.initializer ? classesIn(node.initializer) : '',
        line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
        opening: node.parent.parent,
      })
    }
    node.forEachChild(walk)
  }
  walk(source)
  return found
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
  const source = ts.createSourceFile(
    path,
    readFileSync(path, 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  )
  for (const { text, line, opening } of classNames(source)) {
    if (!CONTROL_CLASS.test(text) || !HEIGHT_UTILITY.test(text)) continue
    if (grows(opening)) continue
    const shown = text.replace(/\s+/g, ' ').slice(0, 76)
    problems.push(`${path.slice(SRC.length + 1)}:${line}  ${shown}`)
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
