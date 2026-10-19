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

/** Every mutation the component declares, read out of the file rather than
 *  listed here. None of their callbacks may write the box: an exemption is the
 *  race this exists to stop, wearing a badge.
 *
 *  Found rather than written down, because a list kept by hand is the bug it
 *  is meant to catch. A fourth mutation added without a line added here, and
 *  everything below would pass while `busy` left it out and Save stayed
 *  pressable through it - which is exactly the race that got in last time.
 */
const MUTATIONS = lines.flatMap((line) => {
  const declared = /const (\w+) = useMutation\(\{/.exec(line)
  return declared ? [declared[1]] : []
})

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

// Asking for a delete has to empty the cached answer along with the box.
//
// Left holding the script, the answer no longer matches the saved text, so
// the box - empty and nobody having touched it - follows it straight back and
// the clear is undone before the request has returned. On a slow delete the
// box then shows the script being deleted and anything typed goes onto the
// end of it. The two writes are one act and the guard keeps them together.
const asked = lines.findIndex((line) => /drop\.mutate\(/.test(line))
if (asked < 0) {
  console.error('\nProjectScript never asks for a delete; this guard needs rewriting.\n')
  process.exit(1)
}
const withRequest = lines.slice(Math.max(0, asked - 22), asked + 1).join('\n')
// And a read already on its way back has to be stopped, or it lands after the
// emptying and puts the script back into the answer - the same bug through a
// second door. This is what TanStack's own optimistic-update guidance says to
// do before writing the cache by hand.
//
// Presence is not the invariant. An un-awaited call does not wait, a call
// after the emptying does not protect it, and a call on another key does not
// touch this read - and each of those would leave prelint reporting the thing
// as held when it is not, which is worse than not checking at all.
const cancel = /await\s+queryClient\.cancelQueries\(\s*\{\s*queryKey:\s*\['project-script',\s*projectId\],?\s*\}\s*\)/.exec(
  withRequest,
)
const emptied = /queryClient\.setQueryData\(\['project-script', projectId\], EMPTY_SCRIPT\)/.exec(
  withRequest,
)
if (!cancel) {
  console.error('\nA delete empties the cached answer without awaiting a cancel of that read:\n')
  console.error('  ProjectScript.tsx:' + (asked + 1) + '  ' + lines[asked].trim())
  console.error('\n  Needs `await queryClient.cancelQueries({ queryKey: [\'project-script\',')
  console.error("  projectId] })` - awaited, on this key. Without the await it does not")
  console.error('  wait; on another key it does not touch the read that overwrites the')
  console.error('  emptying and puts the script back in the answer.\n')
  process.exit(1)
}
if (emptied && cancel.index > emptied.index) {
  console.error('\nA delete cancels the read after emptying the cached answer:\n')
  console.error('  ProjectScript.tsx:' + (asked + 1) + '  ' + lines[asked].trim())
  console.error('\n  The cancel has to come first. After the emptying it cancels nothing')
  console.error('  that could still overwrite it, and the read already out lands on top.\n')
  process.exit(1)
}

if (!emptied) {
  console.error('\nA delete empties the box without emptying the cached answer:\n')
  console.error('  ProjectScript.tsx:' + (asked + 1) + '  ' + lines[asked].trim())
  console.error('\n  Set the cached answer to EMPTY_SCRIPT with the request. Left holding')
  console.error('  the script it no longer matches the saved text, so the untouched box')
  console.error('  follows it back and the clear is undone before the answer returns.\n')
  process.exit(1)
}

// A delete that fails has to put the saved text back along with the answer.
//
// `saved` means what the server holds. The delete empties it with the request,
// so a delete that fails and restores only the answer leaves it empty while
// the script is still there - and that lie reads two ways: `dirty` measures a
// draft against nothing, and `fillWith` sees a script that has been there all
// along as newly saved. The restore is one act, like the emptying.
const rolled = lines.findIndex((line) =>
  /setQueryData\(\['project-script', projectId\], before\)/.test(line),
)
if (rolled < 0) {
  console.error('\nNothing puts the answer back when a delete fails; this guard needs rewriting.\n')
  process.exit(1)
}
const withRollback = lines.slice(rolled, rolled + 26).join('\n')
if (!/setSaved\(before\.text\)/.test(withRollback)) {
  console.error('\nA delete that fails restores the answer but not the saved text:\n')
  console.error('  ProjectScript.tsx:' + (rolled + 1) + '  ' + lines[rolled].trim())
  console.error('\n  Call setSaved(before.text) beside it. The server still holds this')
  console.error('  script, so leaving the saved text empty measures a draft against')
  console.error('  nothing and reads an old script as newly saved.\n')
  process.exit(1)
}

// A delete that fails has to send the editor back to what the project opens
// on, and only when nobody has typed.
//
// Following cannot get there. With nothing saved and a run on record the
// opening text is the run, and following compares the saved text, so the box
// would sit empty with no notice and no offer and the run invisible until a
// reload. Marking the project unfilled sends the next pass down the opening
// branch. The condition is the other half: the opening branch does not ask,
// so without it a replacement somebody had started typing is overwritten.
const reopens = /if \(live\.current === shown\.current\) filledFor\.current = null/.test(
  withRollback,
)
if (!reopens) {
  console.error('\nA delete that fails does not send the editor back to what the project opens on:\n')
  console.error('  ProjectScript.tsx:' + (rolled + 1) + '  ' + lines[rolled].trim())
  console.error('\n  Add `if (live.current === shown.current) filledFor.current = null`.')
  console.error('  Following compares the saved text, so a project with nothing saved and')
  console.error('  a run on record is left with an empty box and no way back to the run.')
  console.error('  The condition keeps the opening branch off a box somebody is typing in.\n')
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

// And the one place that may fill it has to still ask.
if (!/const fill = fillWith\(script\.data, \{/.test(source)) {
  console.error('\nProjectScript no longer fills the box through fillWith; this guard needs rewriting.\n')
  process.exit(1)
}

console.log('the script box is written by the person, not by an answer')
