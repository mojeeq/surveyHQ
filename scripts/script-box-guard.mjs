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
 * `setText` is the person acting - typing, inserting an example, or asking
 * for the recorded run back - and a mutation's callback is not the person.
 *
 * A mutation records what happened by moving `shown` and `saved`, never by
 * writing the box. A delete writes nothing at all: it takes the script away,
 * and the box stops taking keystrokes the moment it is asked for.
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

/** Every mutation the component declares, read out of the file rather than
 *  listed here. None of their callbacks may write the box: an exemption is the
 *  race this exists to stop, wearing a badge.
 *
 *  Found rather than written down, because a list kept by hand is the bug it
 *  is meant to catch. A fourth mutation added without a line added here, and
 *  everything below would pass while `busy` left it out and Save stayed
 *  pressable through it - which is exactly the race that got in last time.
 */
const DECLARED = /const (\w+) = useMutation(?:<[^>]*>)?\s*\(\s*\{/
const MUTATIONS = lines.flatMap((line) => {
  const declared = DECLARED.exec(line)
  return declared ? [declared[1]] : []
})

/** Every call, so a declaration written in a shape the line above does not
 *  read cannot simply go unseen.
 *
 *  Widening that pattern to cover more shapes would be chasing: the next one
 *  is whatever nobody thought of, and the cost of missing it is this guard
 *  quietly not covering a mutation while printing that all is well. So the
 *  calls are counted instead, and one that was not claimed by name is a
 *  failure asking for the guard to be taught the shape - noisy where silence
 *  would be wrong.
 */
const unclaimed = lines.filter(
  // No dot in the lookbehind, unlike the scan below. There the point is to
  // skip a mention that is not a call; here anything that even looks like one
  // and was not claimed by name should be noticed, a namespace-qualified
  // `ReactQuery.useMutation({` included. Leaving the dot out of the net was
  // the difference between failing on what this cannot read and passing over
  // it, which is the whole claim this check makes.
  (line) => /(?<!\w)useMutation\s*[<(]/.test(line) && !DECLARED.test(line),
)
if (unclaimed.length) {
  console.error('\nProjectScript declares a mutation in a shape this guard cannot read:\n')
  for (const line of unclaimed) console.error('  ' + line.trim())
  console.error('\n  It reads `const <name> = useMutation({`, with an optional type')
  console.error('  argument. Anything else leaves the mutation out of both the callback')
  console.error('  scan and the `busy` check, so teach this the shape rather than')
  console.error('  letting it pass over one.\n')
  process.exit(1)
}

/** The ones that have to be there. Not a list of what matters - that is what
 *  the discovery above is for - but a floor under it: a regex that stopped
 *  matching would hand every check below an empty list to pass vacuously,
 *  which is the same failure one level up. */
const FLOOR = ['keep', 'run', 'drop']
const absent = FLOOR.filter((name) => !MUTATIONS.includes(name))
if (absent.length) {
  console.error('\nProjectScript declares no mutation called ' + absent.join(' or ') + '.\n')
  console.error('  Either they were renamed, or the shape this guard reads them by has')
  console.error('  changed and it is now finding: ' + (MUTATIONS.join(', ') || '(nothing)'))
  console.error('  Rewrite the guard rather than leaving it matching nothing.\n')
  process.exit(1)
}

const found = []
for (const name of MUTATIONS) {
  // The same pattern discovery used, so a shape it reads is a shape this
  // finds. Matching a narrower one here would fail on a declaration that was
  // found a moment ago, and say it does not exist.
  const start = lines.findIndex((line) => {
    const declared = DECLARED.exec(line)
    return declared !== null && declared[1] === name
  })
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

// A delete takes the script away rather than emptying it.
//
// It used to empty the box and the cached answer with the request and leave
// the editor open on the project, so that a replacement could be typed
// straight in - which took an awaited cancel of the read in flight, a
// rollback of both halves of the answer when the delete failed, and a branch
// that reopened the project only if nobody had typed, all of it checked here.
// A project can have several scripts now, and deleting one closes it: there
// is nothing left to type a replacement into, and the next script is started
// with New.
//
// So the invariant is the other way round, and each part of it stands in for
// a piece of what was checked before:
//
// - nothing is written ahead of the answer, so a delete that fails has
//   nothing to roll back and the editor is exactly as it was;
// - the box stops taking keystrokes once the delete is asked for, so nothing
//   is typed into a script that is about to be gone;
// - and the draft is not kept again behind the delete, which clears it -
//   or a keystroke landing in between would keep one for no script at all.
const asked = lines.findIndex((line) => /drop\.mutate\(/.test(line))
if (asked < 0) {
  console.error('\nProjectScript never asks for a delete; this guard needs rewriting.\n')
  process.exit(1)
}
const withRequest = lines.slice(Math.max(0, asked - 14), asked + 1)
const ahead = withRequest.filter((line) =>
  /(?<![.\w])(setText|setSaved)\s*\(|setQueryData\s*\(|shown\.current\s*=/.test(line),
)
if (ahead.length) {
  console.error('\nA delete writes the editor ahead of its answer:\n')
  for (const line of ahead) console.error('  ' + line.trim())
  console.error('\n  Deleting a script closes it, so there is nothing to empty. Written')
  console.error('  ahead of the answer, a delete that fails has to put all of it back,')
  console.error('  and the read already out can land on top of the emptying.\n')
  process.exit(1)
}
if (!/readOnly=\{[^}]*drop\.isPending/.test(source)) {
  console.error('\nThe script box still takes keystrokes while a delete is out.\n')
  console.error('  Make the editor read-only on `drop.isPending` (and after it), or what')
  console.error('  is typed then goes into a script that is about to be gone.\n')
  process.exit(1)
}
const kept = lines.findIndex((line) => /(?<![.\w])writeDraft\s*\(/.test(line))
if (kept < 0) {
  console.error('\nProjectScript no longer keeps drafts; this guard needs rewriting.\n')
  process.exit(1)
}
if (!/drop\.isPending/.test(lines.slice(Math.max(0, kept - 8), kept).join('\n'))) {
  console.error('\nA draft can be kept again behind a delete:\n')
  console.error('  ProjectScript.tsx:' + (kept + 1) + '  ' + lines[kept].trim())
  console.error('\n  Leave the draft alone while the delete is out and after it. The')
  console.error('  delete clears it, and keeping it again leaves a draft for no script.\n')
  process.exit(1)
}

// Nothing that fires one of these requests may be pressable while another is
// out, so `busy` has to name every one of them.
//
// The delete was missing from it, and the Delete button made up for the gap at
// its own call site, which hid it: Save stayed live through a delete, so a
// replacement typed and saved sent a PUT racing the DELETE - and where the PUT
// landed first the DELETE removed the script that had just been saved, after
// Save had said it worked. A mutation added later is the same bug again, so
// the list is checked rather than kept in step by hand.
const busy = lines.findIndex((line) => /const busy =/.test(line))
if (busy < 0) {
  console.error('\nProjectScript has no `busy`; this guard needs rewriting.\n')
  process.exit(1)
}
const missing = MUTATIONS.filter((name) => !lines[busy].includes(`${name}.isPending`))
if (missing.length) {
  console.error('\n`busy` does not name every request that changes the script:\n')
  console.error('  ProjectScript.tsx:' + (busy + 1) + '  ' + lines[busy].trim())
  console.error('\n  Missing: ' + missing.map((name) => `${name}.isPending`).join(', '))
  console.error('  Save and Run stay pressable while that request is out, so a second')
  console.error('  one races it. Add it here rather than at a button, which hides the gap.\n')
  process.exit(1)
}

// The saved text and the run the editor knows move together.
//
// They are the two halves of the answer, and `fillWith` compares both to
// decide whether anything has happened since the editor settled on one.
// Moving one without the other makes the pair say something neither half
// meant: leave the run behind and every later answer looks new, so an
// untouched box is rewritten on every refetch; move the run without the saved
// text and a change goes unnoticed.
//
// Checked both ways round. One direction is not the invariant - dropping the
// saved text while keeping the run passes a forward-only check and leaves
// exactly the half-pair this is here to stop.
//
// No test can see any of it. `fillWith` is handed the pair and cannot tell
// whether the component kept it honest; mutating either assignment away
// leaves every test passing.
const halves = [/(?<![.\w])setSaved\s*\(/, /(?<![.\w])knownRun\.current\s*=/]
const lonely = []
for (let i = 0; i < lines.length; i += 1) {
  for (const [which, half] of halves.entries()) {
    if (!half.test(lines[i])) continue
    const other = halves[1 - which]
    const near = lines.slice(Math.max(0, i - 4), i + 5).join('\n')
    if (!other.test(near)) lonely.push(`${i + 1}  ${lines[i].trim()}`)
  }
}
if (lonely.length) {
  console.error('\nOne half of the answer moves without the other:\n')
  for (const hit of lonely) console.error('  ProjectScript.tsx:' + hit)
  console.error('\n  `setSaved` and `knownRun.current` go together. They are the two')
  console.error('  halves of the answer that `fillWith` compares to decide whether')
  console.error('  anything has happened, and half of it moving says something')
  console.error('  neither half meant.\n')
  process.exit(1)
}

// And the effect settles both before it decides not to write the box.
//
// `fillWith` returning null means "leave the box", which is not the same as
// "nothing happened" - an answer can move from a recorded run to a saved
// script of the same text, where there is nothing to write and everything to
// record. Reading the one as the other left the saved text empty against a
// server holding a script, so Save claimed unsaved changes on a box that
// matched it, and clearing the box turned Save off on a project that still
// had one.
const decides = lines.findIndex((line) => /if \(fill === null\) return/.test(line))
if (decides < 0) {
  console.error('\nThe fill effect no longer bails on a null fill; this guard needs rewriting.\n')
  process.exit(1)
}
const beforeDeciding = lines.slice(0, decides).join('\n')
for (const half of halves) {
  if (!half.test(beforeDeciding)) {
    console.error('\nThe fill effect decides not to write the box before settling the answer:\n')
    console.error('  ProjectScript.tsx:' + (decides + 1) + '  ' + lines[decides].trim())
    console.error('\n  Set the saved text and the run from the answer above this line. A')
    console.error('  null fill means the box needs no write, not that nothing happened.\n')
    process.exit(1)
  }
}

// And the one place that may fill it has to still ask.
if (!/const fill = fillWith\(script\.data, \{/.test(source)) {
  console.error('\nProjectScript no longer fills the box through fillWith; this guard needs rewriting.\n')
  process.exit(1)
}

console.log('the script box is written by the person, not by an answer')
