import { describe, expect, it } from 'vitest'

import { insertLine } from '@/lib/script-insert'

/** Where the caret lands, shown in place, so a failure reads as a picture. */
const shown = (text: string, at: number, line: string) => {
  const result = insertLine(text, at, line)
  return result.text.slice(0, result.caret) + '|' + result.text.slice(result.caret)
}

describe('putting an example line into a script', () => {
  it('starts an empty script without a leading blank line', () => {
    expect(shown('', 0, 'use people')).toBe('use people|')
  })

  it('breaks the line somebody is in the middle of typing', () => {
    // The caret sits after "use peo". Appending to that would make "use
    // peouse people", which is the behaviour this exists to avoid.
    expect(shown('use peo', 7, 'collapse (mean) wage')).toBe(
      'use peo\ncollapse (mean) wage|',
    )
  })

  it('inserts in the middle without swallowing what follows', () => {
    expect(shown('use people\nsave as "x"', 11, 'gen adult = age >= 18')).toBe(
      'use people\ngen adult = age >= 18|\nsave as "x"',
    )
  })

  it('leaves no blank line when the caret is already on an empty one', () => {
    // A script ending in a newline is the ordinary case: somebody pressed
    // Enter and is about to type. One line should appear, not a gap and a line.
    expect(shown('use people\n', 11, 'gen adult = age >= 18')).toBe(
      'use people\ngen adult = age >= 18|',
    )
  })

  it('does not run two lines together when inserting before one', () => {
    expect(insertLine('save as "x"', 0, 'use people').text).toBe('use people\nsave as "x"')
  })

  it('leaves the caret at the end of what it inserted, ready to type on', () => {
    const result = insertLine('use people\n', 11, 'gen adult = age >= 18')
    expect(result.text.slice(result.caret)).toBe('')
    expect(result.text.endsWith('gen adult = age >= 18')).toBe(true)
  })

  it('clamps a caret that is not in the text rather than losing the script', () => {
    // A stale ref reports a position from before the text changed. Slicing on
    // it would silently drop characters; this is the cheaper bug to not have.
    expect(insertLine('use people', 999, 'save, replace').text).toBe(
      'use people\nsave, replace',
    )
    expect(insertLine('use people', -5, 'save, replace').text).toBe(
      'save, replace\nuse people',
    )
  })
})
