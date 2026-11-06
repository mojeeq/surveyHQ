/** Putting a line into a script at the caret.
 *
 *  Appending to the end would be wrong half the time: a script is built from
 *  the top down, so the line somebody wants is usually the next one rather than
 *  the last one, and dropping one into the middle should not mean retyping the
 *  rest.
 */
export type Insertion = {
  text: string
  /** Where the caret belongs afterwards: the end of what was inserted. */
  caret: number
}

export function insertLine(text: string, at: number, line: string): Insertion {
  // A caret outside the text is not a thing a textarea produces, but it is
  // what a stale ref produces, and clamping is cheaper than the bug.
  const where = Math.max(0, Math.min(at, text.length))
  const before = text.slice(0, where)
  const after = text.slice(where)
  // On a line of its own, without leaving a blank one behind when the caret was
  // already at the start of an empty line.
  const lead = before === '' || before.endsWith('\n') ? '' : '\n'
  const tail = after === '' || after.startsWith('\n') ? '' : '\n'
  return {
    text: `${before}${lead}${line}${tail}${after}`,
    caret: before.length + lead.length + line.length,
  }
}
