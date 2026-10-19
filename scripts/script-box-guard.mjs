/**
 * Fails if an answer from the server writes the script box directly.
 *
 * The box in ProjectScript is the person's. It stays editable while a request
 * is in flight, so anything a response hands back lands on top of whatever
 * was typed in the meantime, and those keystrokes are gone with nothing said.
 *
 * This has been got wrong twice in a row. First a refetch refilled the box
 * from the query and threw away the draft somebody was correcting. Then the
 * fix for that wrote the saved text back on save, which wiped anything typed
 * while the PUT was in flight - the same mistake one layer along.
 *
 * So there is one place the editor fills the box from an answer: the effect
 * that calls `fillWith`, which decides whether it may. Everywhere else,
 * `setText` is the person acting - typing, inserting an example, clearing
 * after a delete, or asking for the recorded run back - and a mutation's
 * callback is not the person.
 *
 * A mutation records what happened by moving `shown` and `saved`, never by
 * writing the box. Clearing it after a delete is the exception, because there
 * is no longer anything to show and nothing of theirs to lose.
 *
 * Run from `prelint`, so CI catches the next one.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FILE = fileURLToPath(
  new URL('../frontend/src/components/ProjectScript.tsx', import.meta.url),
)

const source = readFileSync(FILE, 'utf8')
const lines = source.split('\n')

/** The mutations whose callbacks must not write the box, and the one write
 *  each is allowed. `drop` empties it: nothing is left to show. */
const ALLOWED = new Map([
  ['keep', []],
  ['run', []],
  ['drop', ["setText('')"]],
])

const found = []
for (const [name, allowed] of ALLOWED) {
  const start = lines.findIndex((line) => line.includes(`const ${name} = useMutation({`))
  if (start < 0) {
    console.error(`\nProjectScript has no \`${name}\` mutation; this guard needs rewriting.\n`)
    process.exit(1)
  }
  // To the end of the useMutation call, which is the first line back at the
  // mutation's own indentation closing it.
  let end = lines.length
  for (let i = start + 1; i < lines.length; i += 1) {
    if (/^ {2}\}\)\s*$/.test(lines[i])) {
      end = i
      break
    }
  }
  for (let i = start; i < end; i += 1) {
    const line = lines[i].trim()
    if (!/(?<![.\w])setText\s*\(/.test(line)) continue
    if (allowed.some((ok) => line.includes(ok))) continue
    found.push(`${i + 1}  ${line}  (in \`${name}\`)`)
  }
}

if (found.length) {
  console.error('\nAn answer from the server writes the script box:\n')
  for (const hit of found) console.error('  ProjectScript.tsx:' + hit)
  console.error('\n  The box stays editable while the request is in flight, so this')
  console.error('  lands on top of anything typed in the meantime and loses it.')
  console.error('  Move `shown` and `saved` instead and let the fill effect decide,')
  console.error('  which is what `fillWith` is for.\n')
  process.exit(1)
}

// And the one place that may fill it has to still ask.
if (!/const fill = fillWith\(script\.data, \{/.test(source)) {
  console.error('\nProjectScript no longer fills the box through fillWith; this guard needs rewriting.\n')
  process.exit(1)
}

console.log('the script box is written by the person, not by an answer')
