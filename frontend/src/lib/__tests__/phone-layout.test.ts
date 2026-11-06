import { describe, expect, it } from 'vitest'

import { stackForPhone } from '../phone-layout'

const at = (i: string, x: number, y: number, w = 6, h = 4) => ({ i, x, y, w, h })

describe('a board on a phone', () => {
  it('stacks every widget full width, top to bottom and left to right', () => {
    const stacked = stackForPhone([at('b', 6, 0), at('a', 0, 0), at('c', 0, 4, 12, 3)], 12, () => undefined)
    expect(stacked.map((item) => item.i)).toEqual(['a', 'b', 'c'])
    expect(stacked.map((item) => [item.x, item.y, item.w])).toEqual([
      [0, 0, 12],
      [0, 4, 12],
      [0, 8, 12],
    ])
  })

  it('keeps a group together, its heading first', () => {
    // Two groups side by side, each a heading over two widgets.
    const items = [
      at('group:left', 0, 0, 6, 1),
      at('l1', 0, 1, 3, 4),
      at('l2', 3, 1, 3, 4),
      at('group:right', 6, 0, 6, 1),
      at('r1', 6, 1, 6, 4),
      at('after', 0, 5, 12, 4),
    ]
    const groupOf = (id: string) =>
      id.startsWith('l') ? 'group:left' : id === 'r1' ? 'group:right' : undefined
    const stacked = stackForPhone(items, 12, groupOf)
    expect(stacked.map((item) => item.i)).toEqual([
      'group:left',
      'l1',
      'l2',
      'group:right',
      'r1',
      'after',
    ])
    // Nothing overlaps: each starts where the last ended.
    stacked.slice(1).forEach((item, index) => {
      const before = stacked[index]
      expect(item.y).toBe(before.y + before.h)
    })
  })

  it('keeps each widget its height', () => {
    const stacked = stackForPhone([at('tall', 0, 0, 6, 9)], 12, () => undefined)
    expect(stacked[0].h).toBe(9)
  })
})
