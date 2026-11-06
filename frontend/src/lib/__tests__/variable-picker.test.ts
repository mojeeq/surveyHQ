/**
 * Browsing a long variable list to its end.
 *
 * The list used to stop at 200 rows with nothing saying so, which on a census
 * form means most of the questionnaire could only be reached by typing enough
 * of a variable's name to find it. The two decisions that make scrolling and
 * the arrow keys carry on are pure, and are checked here; that the rows then
 * appear is checked against the running app.
 */
import { describe, expect, it } from 'vitest'

import { nearEnd, PAGE, walked } from '@/components/explore/VariablePicker'

describe('walking the list with the arrows', () => {
  it('moves down a row', () => {
    expect(walked(3, 1, 10, false)).toEqual({ active: 4, reveal: false })
  })

  it('moves up a row', () => {
    expect(walked(3, -1, 10, false)).toEqual({ active: 2, reveal: false })
  })

  it('asks for more rows at the end of a list that has them', () => {
    // The fault: this used to wrap to the top, so holding the arrow down
    // walked to the last drawn row and started again, past nothing.
    expect(walked(99, 1, 100, true)).toEqual({ active: 100, reveal: true })
  })

  it('wraps to the top at the end of a list that has no more', () => {
    expect(walked(99, 1, 100, false)).toEqual({ active: 0, reveal: false })
  })

  it('wraps to the bottom going up from the first row', () => {
    expect(walked(0, -1, 10, false)).toEqual({ active: 9, reveal: false })
    // More rows behind the fold is not a reason to go anywhere else: up from
    // the top goes to the last row that is drawn.
    expect(walked(0, -1, 10, true)).toEqual({ active: 9, reveal: false })
  })

  it('stays put on a list with nothing in it', () => {
    expect(walked(0, 1, 0, false)).toEqual({ active: 0, reveal: false })
    expect(walked(0, -1, 0, false)).toEqual({ active: 0, reveal: false })
  })
})

describe('scrolling the list', () => {
  // The dropdown is 256px tall, and a row is about 30px.
  const box = (scrollTop: number, scrollHeight: number) => ({
    scrollTop,
    clientHeight: 256,
    scrollHeight,
  })

  it('wants nothing at the top of a long list', () => {
    expect(nearEnd(box(0, 3000))).toBe(false)
  })

  it('wants more a screen before the end, not at it', () => {
    // Asking only once the fold is reached means the rows arrive after the
    // scrolling has already stopped against the bottom.
    expect(nearEnd(box(3000 - 256 - 200, 3000))).toBe(true)
  })

  it('wants more at the bottom', () => {
    expect(nearEnd(box(3000 - 256, 3000))).toBe(true)
  })

  it('wants more when everything fits already', () => {
    // Harmless: the caller only asks when rows are left over, and a list
    // shorter than its own box has none.
    expect(nearEnd(box(0, 200))).toBe(true)
  })
})

describe('the page size', () => {
  it('is more than one screen of rows', () => {
    expect(PAGE).toBeGreaterThan(8)
  })
})
