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
 * writing the box - the delete included. Emptying the box after a delete is
 * the person's own action and happens where they ask for it, with the
 * request, because by the time the answer gets back they may have started
 * typing the script that replaces the one they removed.
 *
 * What this does not catch: a callback that writes the box through a helper
 * rather than calling `setText` itself. Following that would want the call
 * graph, which is more than this is worth; it is named here so the next
 * person knows the edge rather than trusting a clean run too far.
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

/** The mutations whose callbacks must not write the box. None of them may:
 *  an exemption here is the race the guard exists to stop, wearing a badge. */
const MUTATIONS = ['keep', 'run', 'drop']

const found = []
for (const name of MUTATIONS) {
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
