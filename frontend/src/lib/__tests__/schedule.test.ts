import { describe, expect, it } from 'vitest'
import { readySchedule } from '@/lib/schedule'
import type { SnapshotSchedule } from '@/lib/types'

const BLANK: SnapshotSchedule = {
  enabled: false,
  times: ['08:00'],
  days: [],
  timezone: 'UTC',
  keep: 12,
}

describe('readySchedule', () => {
  it('fills a time in, so the form saves what it shows', () => {
    // The bug this exists for: the server returns no times, the input renders
    // a fallback, and saving sends [] - which the server refuses.
    const ready = readySchedule({ ...BLANK, enabled: true, times: [] }, BLANK)
    expect(ready.times).toEqual(['08:00'])
  })

  it('leaves a time that was actually stored alone', () => {
    const ready = readySchedule({ ...BLANK, times: ['17:30'] }, BLANK)
    expect(ready.times).toEqual(['17:30'])
  })

  it('never hands back a keep of zero', () => {
    expect(readySchedule({ ...BLANK, keep: 0 }, BLANK).keep).toBe(12)
    expect(readySchedule({ ...BLANK, keep: 3 }, BLANK).keep).toBe(3)
  })

  it('is the blank schedule when nothing is stored', () => {
    expect(readySchedule(null, BLANK)).toEqual(BLANK)
    expect(readySchedule(undefined, BLANK)).toEqual(BLANK)
  })

  it('keeps the days and zone it was given', () => {
    const ready = readySchedule(
      { ...BLANK, days: [0, 3], timezone: 'Pacific/Efate', times: [] },
      BLANK,
    )
    expect(ready.days).toEqual([0, 3])
    expect(ready.timezone).toBe('Pacific/Efate')
  })
})
