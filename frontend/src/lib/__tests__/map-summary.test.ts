import { describe, expect, it } from 'vitest'

import { mapSummary } from '@/lib/format'

describe('what a map says its pins stand for', () => {
  it('counts locations when every one is drawn where it was recorded', () => {
    expect(mapSummary(1840)).toBe('1,840 location(s)')
  })

  it('says nothing is located rather than drawing a zero', () => {
    expect(mapSummary(0)).toBe('No located interviews')
    expect(mapSummary(0, { records: 12000, metres: 110 })).toBe('No located interviews')
  })

  it('leads with the interviews, because that is the number being asked about', () => {
    // A pin on a census map is a cell of ground. "1,509 pins" alone reads as
    // 1,509 interviews to anybody who does not know that.
    expect(mapSummary(1509, { records: 100000, metres: 1100 })).toBe(
      '100,000 located interviews, drawn as 1,509 pins about 1.1 km across',
    )
  })

  it('stays in metres while a cell is smaller than a kilometre', () => {
    expect(mapSummary(3800, { records: 42000, metres: 110 })).toBe(
      '42,000 located interviews, drawn as 3,800 pins about 110 m across',
    )
  })
})
