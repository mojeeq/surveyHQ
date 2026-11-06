/**
 * The room between two groups is the room between two widgets.
 *
 * A group's frame was drawn 10px outside its widgets, into the 16px gutter
 * between grid cells. Two groups side by side then met in the middle of it -
 * their lines overlapped - and a widget beside a group sat 6px from its line.
 * The frame now lies on the grid's own lines and the widgets are moved in from
 * it on the sides that lie on it, so the gutter round a group is the gutter
 * round any widget.
 */
import type { Layout } from 'react-grid-layout'
import { describe, expect, it } from 'vitest'

import {
  GROUP_INSET,
  GROUP_LINE,
  barStyles,
  groupItemId,
  insetPadding,
  insets,
  pixels,
} from '@/components/dashboard/WidgetGroups'
import type { WidgetGroup } from '@/lib/types'

const group = (id: string, extra: Partial<WidgetGroup> = {}): WidgetGroup =>
  ({ id, name: id.toUpperCase(), collapsed: false, ...extra }) as WidgetGroup

const item = (i: string, x: number, y: number, w: number, h: number): Layout => ({ i, x, y, w, h })

// Two groups side by side, six columns each. The left one has two tiles side
// by side and one under them; the right one a single tall chart.
const left = group('left')
const right = group('right')
const layout: Layout[] = [
  item(groupItemId(left), 0, 0, 6, 1),
  item('a', 0, 1, 3, 4),
  item('b', 3, 1, 3, 4),
  item('c', 0, 5, 4, 3),
  item(groupItemId(right), 6, 0, 6, 1),
  item('d', 6, 1, 6, 7),
]
const members: Record<string, string[]> = { left: ['a', 'b', 'c'], right: ['d'] }
const membersOf = (id: string) => members[id] ?? []

describe('which sides of a grouped widget lie on its frame', () => {
  const found = insets([left, right], layout, membersOf)

  it('moves in the sides on the frame and leaves the inner ones alone', () => {
    // a: left edge of the group; its right side faces b, inside the group.
    expect(found.get('a')).toEqual({ left: true, right: false, bottom: false })
    // b: right edge, but c reaches lower, so b is not at the foot.
    expect(found.get('b')).toEqual({ left: false, right: true, bottom: false })
    // c: left edge and the foot; its right side is open space in the group.
    expect(found.get('c')).toEqual({ left: true, right: false, bottom: true })
    // d fills its group: every side but the top, where the bar is.
    expect(found.get('d')).toEqual({ left: true, right: true, bottom: true })
  })

  it('moves nothing in a folded group, which has no frame', () => {
    const folded = insets([{ ...left, collapsed: true }, right], layout, membersOf)
    expect(folded.has('a')).toBe(false)
    expect(folded.has('d')).toBe(true)
  })

  it('leaves a widget in no group as the grid placed it', () => {
    const loose = insets([left], [...layout, item('e', 0, 8, 4, 3)], membersOf)
    expect(loose.has('e')).toBe(false)
    expect(insetPadding(loose.get('e'))).toBeUndefined()
  })

  it('turns the sides into padding', () => {
    expect(insetPadding(found.get('c'))).toEqual({
      paddingLeft: GROUP_INSET,
      paddingRight: 0,
      paddingBottom: GROUP_INSET,
    })
  })
})

describe('the frame on the grid', () => {
  const grid = { columns: 12, rowHeight: 40, canvasWidth: 1232, margin: 16, padding: 16 }

  it('leaves the grid gutter between two groups side by side', () => {
    // The frames are the cells' own boxes, so the space between them is the
    // space between any two cells - not the 16px less two insets it was.
    const one = pixels({ x: 0, y: 0, w: 6, h: 8 }, grid)
    const two = pixels({ x: 6, y: 0, w: 6, h: 8 }, grid)
    expect(two.left - (one.left + one.width)).toBe(grid.margin)
  })
})

describe('the bar of a group', () => {
  it('sits inside the frame line of an open group, with a rule under it', () => {
    const { cell, strip } = barStyles(group('g', { color: '#123456', background: '#fdf6e3' }))
    expect(cell.padding).toBe(`${GROUP_LINE}px ${GROUP_LINE}px 0`)
    expect(strip.borderBottom).toBe('1px dashed #123456')
    expect(strip.border).toBeUndefined()
    expect(strip.backgroundColor).toBe('#fdf6e3')
  })

  it('is a box of its own when the group is folded', () => {
    const { cell, strip } = barStyles(group('g', { collapsed: true }), 'rgb(1 2 3)')
    expect(cell.padding).toBeUndefined()
    expect(strip.border).toBe('1px dashed rgb(1 2 3)')
  })
})
