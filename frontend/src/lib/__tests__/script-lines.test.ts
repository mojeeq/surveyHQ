/**
 * Pointing at the line a failed run stopped on.
 *
 * The run counts commands and the box counts lines, and the two part company
 * at the first comment. These are the cases where they do, checked against
 * what the engine's own splitter makes of the same text.
 */
import { describe, expect, it } from 'vitest'

import { caretAt, commandStarts, failedLine } from '@/lib/script-lines'

describe('where each command starts', () => {
  it('skips comment lines and blank ones', () => {
    const text = '* Read the people file\n\nuse people\n// a note\ngen adult = age >= 18'
    expect(commandStarts(text)).toEqual([3, 5])
  })

  it('counts a command continued with /// from its first line', () => {
    const text = 'use people\ngen score = a + ///\n    b + ///\n    c\nsave, replace'
    expect(commandStarts(text)).toEqual([1, 2, 5])
  })

  it('takes a trailing // as a comment but not one inside quotes', () => {
    const text = 'use people // the main file\ngen site = "https://example.org"'
    expect(commandStarts(text)).toEqual([1, 2])
  })

  it('reads Windows line endings as lines', () => {
    expect(commandStarts('use people\r\n* note\r\ndrop age')).toEqual([1, 3])
  })
})

describe('the line a complaint points at', () => {
  const text = '* Prepare\nuse people\nmerge 1:1 hhid using nowhere\nsave, replace'

  it('is the line the named command starts on', () => {
    expect(failedLine("Line 2 (merge 1:1 hhid using nowhere): no dataset called 'nowhere'", text)).toBe(3)
  })

  it('is nothing for a complaint that names no line', () => {
    expect(failedLine('There is nothing to run', text)).toBeNull()
  })

  it('is nothing when the box has fewer commands than the complaint counts', () => {
    expect(failedLine('Line 9 (drop x): no variable x', text)).toBeNull()
  })
})

describe('the caret, as a status bar shows it', () => {
  it('counts lines and columns from one', () => {
    expect(caretAt('use people\ngen x = 1', 0)).toEqual({ line: 1, column: 1 })
    expect(caretAt('use people\ngen x = 1', 14)).toEqual({ line: 2, column: 4 })
  })

  it('holds to the text for an offset past its end', () => {
    expect(caretAt('ab', 99)).toEqual({ line: 1, column: 3 })
  })
})
