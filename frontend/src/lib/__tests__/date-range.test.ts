/**
 * A dashboard's date-range filter, as the browser works it out.
 *
 * RANGES are the same cases backend/tests/test_date_ranges.py checks: the
 * browser works out the live page's ranges and the server works out a saved
 * view's file, and the two must agree on what "last 7 days" was.
 */
import { describe, expect, it } from 'vitest'

import { toFilterGroup } from '@/components/DashboardFilters'
import { dateBounds, dateConditions, iso, rangeParts, rangeValue } from '@/lib/date-range'
import type { Day } from '@/lib/date-range'

const THURSDAY: Day = { year: 2026, month: 11, date: 12 }

const RANGES: [string, Day, string | null, string | null][] = [
  ['dates:today', THURSDAY, '2026-11-12', '2026-11-13'],
  ['dates:yesterday', THURSDAY, '2026-11-11', '2026-11-12'],
  ['dates:last_7', THURSDAY, '2026-11-06', '2026-11-13'],
  ['dates:last_30', THURSDAY, '2026-10-14', '2026-11-13'],
  ['dates:this_week', THURSDAY, '2026-11-09', '2026-11-13'],
  ['dates:this_month', THURSDAY, '2026-11-01', '2026-11-13'],
  ['dates:last_month', THURSDAY, '2026-10-01', '2026-11-01'],
  ['dates:last_month', { year: 2026, month: 1, date: 5 }, '2025-12-01', '2026-01-01'],
  ['dates:2026-11-01..2026-11-15', THURSDAY, '2026-11-01', '2026-11-16'],
  ['dates:..2026-11-15', THURSDAY, null, '2026-11-16'],
  ['dates:2026-11-01..', THURSDAY, '2026-11-01', null],
]

describe('what each choice means', () => {
  it.each(RANGES)('%s on %o', (choice, today, first, after) => {
    const bounds = dateBounds(choice, today)
    expect(bounds.first ? iso(bounds.first) : null).toBe(first)
    expect(bounds.after ? iso(bounds.after) : null).toBe(after)
  })
})

describe('the conditions a choice makes', () => {
  it('is on or after the first day and before the day after the last', () => {
    expect(dateConditions('when', 'dates:2026-11-03..2026-11-05', THURSDAY)).toEqual([
      { variable: 'when', operator: 'on_or_after', value: '2026-11-03' },
      { variable: 'when', operator: 'before', value: '2026-11-06' },
    ])
  })

  it('sits beside the dropdowns in the page filter', () => {
    const group = toFilterGroup(
      [
        { variable: 'province', dataset_id: 'd' },
        { variable: 'when', dataset_id: 'd', kind: 'dates' },
      ],
      { province: 'Northern', when: 'dates:today' },
      new Date(2026, 10, 12, 15, 0),
    )
    expect(group.conditions).toEqual([
      { variable: 'province', operator: 'eq', value: 'Northern', use_label: true },
      { variable: 'when', operator: 'on_or_after', value: '2026-11-12' },
      { variable: 'when', operator: 'before', value: '2026-11-13' },
    ])
  })

  it('narrows nothing where nothing is chosen', () => {
    expect(toFilterGroup([{ variable: 'when', dataset_id: 'd', kind: 'dates' }], {}).conditions).toEqual([])
  })
})

describe('a range of your own', () => {
  it('round-trips through the two boxes', () => {
    expect(rangeValue('2026-11-01', '2026-11-15')).toBe('dates:2026-11-01..2026-11-15')
    expect(rangeParts('dates:2026-11-01..2026-11-15')).toEqual({ from: '2026-11-01', to: '2026-11-15' })
    expect(rangeParts('dates:last_7')).toEqual({ from: '', to: '' })
    expect(rangeValue('', '')).toBe('')
  })
})
