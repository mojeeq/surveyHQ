/**
 * A group's heading drawn above its widgets, whatever its stored row says.
 *
 * The grid packs everything upwards in order of stored rows, the title bar
 * included. Dragging a widget saved where every widget had been packed to and
 * not where the bar had, so the bar's stored row was left below its members'
 * and the next load packed it after them: the heading at the foot of its own
 * group.
 */
import { describe, expect, it } from 'vitest'

import { GROUP_BAR_ROWS, barsAbove } from '@/components/dashboard/WidgetGroups'

describe('where a group bar is placed', () => {
  it('goes above its members when its stored row has fallen below them', () => {
    const { bars, push } = barsAbove([{ id: 'g1', y: 20 }], [
      { groupId: 'g1', y: 5 },
      { groupId: 'g1', y: 9 },
    ])
    expect(bars.get('g1')).toBe(5 - GROUP_BAR_ROWS)
    expect(push.size).toBe(0)
  })

  it('stays where it is stored when that is already above them', () => {
    const { bars } = barsAbove([{ id: 'g1', y: 2 }], [{ groupId: 'g1', y: 6 }])
    expect(bars.get('g1')).toBe(2)
  })

  it('takes the top row and moves its members down when they start on it', () => {
    const { bars, push } = barsAbove([{ id: 'g1', y: 4 }], [{ groupId: 'g1', y: 0 }])
    expect(bars.get('g1')).toBe(0)
    expect(push.get('g1')).toBe(GROUP_BAR_ROWS)
  })

  it('leaves an empty group, and other groups, as they are stored', () => {
    const { bars, push } = barsAbove(
      [
        { id: 'empty', y: 7 },
        { id: 'g2', y: 1 },
      ],
      [{ groupId: 'g2', y: 3 }],
    )
    expect(bars.get('empty')).toBe(7)
    expect(bars.get('g2')).toBe(1)
    expect(push.size).toBe(0)
  })
})
