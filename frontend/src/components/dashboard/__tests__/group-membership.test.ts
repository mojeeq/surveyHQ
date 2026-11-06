/**
 * Moving widgets into and out of a group.
 *
 * Joining and leaving went through a widget's menu alone. A widget dragged
 * into a group's box sat there as a stranger the box was drawn round, a member
 * dragged out took the box with it, and one taken out through the menu stayed
 * where it stood - inside the box, so it looked as if nothing had happened.
 */
import { describe, expect, it } from 'vitest'

import { GROUP_BAR_ROWS, groupAt, spotBelow, type PlacedGroup } from '@/components/dashboard/WidgetGroups'

// A group nine columns wide at the top of the page, with two tiles under it.
const group: PlacedGroup = {
  id: 'g1',
  bar: { x: 0, y: 0, w: 9, h: GROUP_BAR_ROWS },
  members: [
    { x: 0, y: 1, w: 3, h: 4 },
    { x: 3, y: 1, w: 3, h: 6 },
  ],
}

describe('dropping a widget', () => {
  it('puts it in the group whose box it lands in', () => {
    expect(groupAt({ x: 6, y: 1, w: 3, h: 4 }, [group])).toBe('g1')
    expect(groupAt({ x: 0, y: 5, w: 3, h: 2 }, [group])).toBe('g1')
  })

  it('leaves it out when it lands beside the box or below it', () => {
    expect(groupAt({ x: 9, y: 1, w: 3, h: 4 }, [group])).toBe('')
    // The foot of the group: just below it, which is where "take out" goes.
    expect(groupAt({ x: 0, y: 7, w: 3, h: 4 }, [group])).toBe('')
  })

  it('judges it by its middle, so a widget straddling the edge goes where most of it is', () => {
    expect(groupAt({ x: 7, y: 1, w: 3, h: 4 }, [group])).toBe('g1') // middle at 8.5
    expect(groupAt({ x: 8, y: 1, w: 4, h: 4 }, [group])).toBe('') // middle at 10
  })

  it('takes a widget dropped straight under an empty group', () => {
    const empty: PlacedGroup = { id: 'g2', bar: { x: 0, y: 10, w: 6, h: GROUP_BAR_ROWS }, members: [] }
    expect(groupAt({ x: 0, y: 11, w: 3, h: 4 }, [empty])).toBe('g2')
    expect(groupAt({ x: 0, y: 12, w: 3, h: 4 }, [empty])).toBe('')
  })

  it('chooses the nearest bar above when two groups share columns', () => {
    const lower: PlacedGroup = { id: 'g3', bar: { x: 0, y: 8, w: 9, h: 1 }, members: [{ x: 0, y: 9, w: 3, h: 4 }] }
    expect(groupAt({ x: 3, y: 9, w: 3, h: 4 }, [group, lower])).toBe('g3')
  })
})

describe('taking a widget out', () => {
  it('sets it down below the group, under its tallest member', () => {
    expect(spotBelow({ w: 3, h: 4 }, group, 12)).toEqual({ x: 3, y: 7, w: 3, h: 4 })
    // Which is outside the group by the same rule a drop is judged by.
    expect(groupAt(spotBelow({ w: 3, h: 4 }, group, 12), [group])).toBe('')
  })

  it('sets it straight under the bar when nothing else is left in the group', () => {
    const alone: PlacedGroup = { ...group, members: [] }
    expect(spotBelow({ w: 4, h: 4 }, alone, 12)).toEqual({ x: 0, y: 1, w: 4, h: 4 })
  })

  it('keeps a wide widget on the board', () => {
    const atTheEdge: PlacedGroup = { id: 'g', bar: { x: 8, y: 0, w: 4, h: 1 }, members: [{ x: 9, y: 1, w: 3, h: 4 }] }
    expect(spotBelow({ w: 6, h: 4 }, atTheEdge, 12).x).toBe(6)
  })
})
