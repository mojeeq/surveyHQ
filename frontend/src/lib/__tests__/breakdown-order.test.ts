/**
 * The order the groups of a breakdown are drawn in.
 *
 * Unordered, a chart of sixty enumeration areas answers neither of the two
 * questions anybody brings to it: which areas are behind, and where is this
 * one. These cover each order doing what it says, and the two cases that are
 * easy to get wrong - a group with no quota, which is not behind and not
 * finished, and a board with no quotas at all, where "behind" means nothing.
 */
import { describe, expect, it } from 'vitest'
import { orderBreakdown, type Progress } from '@/lib/breakdown-order'

const groups: [string, number][] = [
  ['0302', 19],
  ['0101', 5],
  ['0805', 2],
  ['4302', 80],
]

const progress: Record<string, Progress> = {
  '0302': { value: 19, target: 60, percent: 31.7 },
  '0101': { value: 5, target: 100, percent: 5 },
  '0805': { value: 2, target: 4, percent: 50 },
  '4302': { value: 80, target: 80, percent: 100 },
}

const names = (rows: [string, number][]) => rows.map(([key]) => key)

describe('orderBreakdown', () => {
  it('puts the group furthest from its own quota first, by default', () => {
    expect(names(orderBreakdown(groups, progress))).toEqual(['0101', '0302', '0805', '4302'])
  })

  it('turns that around for the most complete first', () => {
    expect(names(orderBreakdown(groups, progress, 'done'))).toEqual([
      '4302',
      '0805',
      '0302',
      '0101',
    ])
  })

  it('orders by the count where that is what is asked for', () => {
    expect(names(orderBreakdown(groups, progress, 'largest'))).toEqual([
      '4302',
      '0302',
      '0101',
      '0805',
    ])
  })

  it('orders by name the way a reader looks one up', () => {
    expect(names(orderBreakdown(groups, progress, 'name'))).toEqual([
      '0101',
      '0302',
      '0805',
      '4302',
    ])
  })

  it('leaves the list it was given alone', () => {
    const mine: [string, number][] = [...groups]

    orderBreakdown(mine, progress)

    expect(mine).toEqual(groups)
  })

  it('sends a group with no quota to the end rather than to the top', () => {
    // It is not behind and it is not finished - it is not being judged, and a
    // chart asking who needs help should not open with it.
    const some: Record<string, Progress> = {
      ...progress,
      '0805': { value: 2, target: null, percent: null },
    }

    expect(names(orderBreakdown(groups, some))).toEqual(['0101', '0302', '4302', '0805'])
  })

  it('falls back to the largest where nothing has a quota', () => {
    const none: Record<string, Progress> = Object.fromEntries(
      groups.map(([key, value]) => [key, { value, target: null, percent: null }]),
    )

    expect(names(orderBreakdown(groups, none))).toEqual(['4302', '0302', '0101', '0805'])
  })

  it('reads a group the progress says nothing about at all', () => {
    expect(names(orderBreakdown(groups, {}))).toEqual(['4302', '0302', '0101', '0805'])
  })
})
