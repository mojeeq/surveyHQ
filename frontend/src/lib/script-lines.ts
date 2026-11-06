/** Which line of the box a script's commands start on.
 *
 *  A failed run names a command - "Line 4 (merge 1:1 hhid using people): ..."
 *  - and the four is a count of commands, not of lines in the box. The engine
 *  skips `*` comment lines and blank ones and joins a line ending `///` to the
 *  next, so in any script with a comment at the top the two counts disagree,
 *  and marking the fourth line of the box marks the wrong one.
 *
 *  So this is the engine's splitter (`_lines` in app/services/stata.py) again,
 *  answering where each command began rather than what it says. A second copy
 *  of that rule is a risk, which is why it is only ever used to point at a
 *  line: if the two drift, the mark lands a line out and nothing runs
 *  differently.
 */

/** Where a `//` comment starts on this line, or null. Scanned, so a `//`
 *  inside a quoted string - an address, say - is not taken for one. */
function commentAt(line: string): number | null {
  let quoted = false
  for (let index = 0; index < line.length; index += 1) {
    if (line[index] === '"') quoted = !quoted
    else if (!quoted && line.startsWith('//', index)) return index
  }
  return null
}

/** Each command, as the engine will read it, with the line it starts on. */
export function commandsOf(text: string): { line: number; text: string }[] {
  const found: { line: number; text: string }[] = []
  // The command being continued with `///`, and the line it began on.
  let open: { line: number; text: string } | null = null
  text.split(/\r\n|\r|\n/).forEach((raw, index) => {
    const line = raw.trim()
    if (line.startsWith('*')) return
    let body = line
    const marker = commentAt(line)
    if (marker !== null) {
      const head = line.slice(0, marker).trim()
      if (line.slice(marker).startsWith('///')) {
        open = open
          ? { line: open.line, text: `${open.text} ${head}`.trim() }
          : { line: index + 1, text: head }
        return
      }
      body = head
    }
    if (!body) return
    found.push(open ? { line: open.line, text: `${open.text} ${body}`.trim() } : { line: index + 1, text: body })
    open = null
  })
  if (open !== null) found.push(open)
  return found
}

/** The line, counted from one, that each command starts on. */
export function commandStarts(text: string): number[] {
  return commandsOf(text).map((one) => one.line)
}

/** The line of the box a run's complaint points at, or null when it names
 *  none or the box no longer has that many commands. */
export function failedLine(error: string, text: string): number | null {
  const named = /^Line (\d+) \(/.exec(error)
  if (!named) return null
  return commandStarts(text)[Number(named[1]) - 1] ?? null
}

/** Line and column of a caret, both counted from one, as an editor's status
 *  bar shows them. */
export function caretAt(text: string, offset: number): { line: number; column: number } {
  const before = text.slice(0, Math.max(0, Math.min(offset, text.length))).split('\n')
  return { line: before.length, column: before[before.length - 1].length + 1 }
}
