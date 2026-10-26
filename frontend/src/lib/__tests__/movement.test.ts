/**
 * The lines under an indicator's number: how it moved and where it is going.
 *
 * The server decides which figures the history supports; these fix how the
 * figures that came back are worded, and that a figure missing stays missing
 * rather than being said as nought.
 */
import { describe, expect, it } from 'vitest'

import { movementLines, signed } from '@/lib/movement'

const count = { format: 'number', unit: '', direction: 'higher_is_better', target: 15040 }

/** A day as the reader's browser writes it - 18 Nov, or Nov 18. */
const day = (year: number, month: number, date: number) =>
  new Date(year, month - 1, date).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

describe('how an indicator moved', () => {
  it('says the change since yesterday and in a week', () => {
    const lines = movementLines({ change_day: 212, change_week: 1340 }, count)
    expect(lines[0]).toEqual({ text: '+212 since yesterday · +1,340 in a week', tone: 'good' })
  })

  it('reads a fall as good news where lower is better', () => {
    const lines = movementLines({ change_day: -3 }, { ...count, direction: 'lower_is_better' })
    expect(lines[0].tone).toBe('good')
  })

  it('says no change rather than +0', () => {
    expect(movementLines({ change_day: 0 }, count)[0].text).toBe('No change since yesterday')
  })

  it('moves a percentage in points', () => {
    expect(signed(2.1, 'percent', '')).toBe('+2.1 pts')
    expect(signed(-12, 'number', 'FJD')).toBe('-12 FJD')
  })

  it('says nothing where the history supports nothing', () => {
    expect(movementLines({ change_day: null, change_week: null, pace_per_day: null }, count)).toEqual([])
    expect(movementLines(undefined, count)).toEqual([])
  })
})

describe('where it is heading', () => {
  it('says when the pace reaches the target', () => {
    const lines = movementLines(
      { pace_per_day: 190, projected_at: '2026-11-18T09:00:00+00:00' },
      count,
    )
    expect(lines.at(-1)?.text).toBe(`At 190 a day, reaches 15,040 on ${day(2026, 11, 18)}`)
  })

  it('with a date, says whether that is in time, and what it takes if not', () => {
    const late = movementLines(
      {
        pace_per_day: 190,
        projected_at: '2026-12-02T09:00:00+00:00',
        target_date: '2026-11-30',
        on_course: false,
        days_left: 20,
        needed_per_day: 240,
      },
      count,
    )
    expect(late.map((line) => line.text)).toEqual([
      `At 190 a day, reaches 15,040 on ${day(2026, 12, 2)}, after ${day(2026, 11, 30)}`,
      `Needs 240 a day to make ${day(2026, 11, 30)}`,
    ])
    expect(late[0].tone).toBe('bad')

    const early = movementLines(
      { pace_per_day: 300, projected_at: '2026-11-20T09:00:00+00:00', target_date: '2026-11-30', on_course: true, days_left: 20, needed_per_day: 240 },
      count,
    )
    expect(early).toEqual([{ text: expect.stringMatching(/, in time$/), tone: 'good' }])
  })

  it('says a pace going nowhere, and a date that has passed', () => {
    const lines = movementLines(
      { pace_per_day: -4, target_date: '2026-11-01', days_left: -2 },
      count,
    )
    expect(lines.map((line) => line.text)).toEqual([
      'Not moving towards the target this week',
      `The target date, ${day(2026, 11, 1)}, has passed`,
    ])
  })

  it('projects nothing past the target, and only a pace where there is none', () => {
    expect(movementLines({ reached: true, pace_per_day: 50 }, count)).toEqual([])
    expect(movementLines({ pace_per_day: 50 }, { ...count, target: null })).toEqual([
      { text: 'Averaging +50 a day', tone: 'plain' },
    ])
  })
})
