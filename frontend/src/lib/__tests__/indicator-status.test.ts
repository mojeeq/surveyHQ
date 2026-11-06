import { describe, expect, it } from 'vitest'

import { indicatorBadge } from '../indicator-status'

describe('the badge an indicator wears', () => {
  it('is decided by the thresholds where there are some', () => {
    expect(indicatorBadge({ status: 'ok', target_value: 600, judged: true }).label).toBe('On track')
    expect(indicatorBadge({ status: 'warning', target_value: 600, judged: true }).label).toBe('Watch')
    expect(indicatorBadge({ status: 'critical', target_value: null, judged: true }).label).toBe('Critical')
  })

  it('does not claim "on track" for an indicator nothing was asked of', () => {
    // No target and no thresholds: "ok" is only the default.
    const none = indicatorBadge({ status: 'ok', target_value: null, judged: false })
    expect(none.label).toBe('No target')
    expect(none.tone).toBe('neutral')
    expect(none.title).toMatch(/thresholds/)
    // A target but no thresholds: the bar shows the progress, the badge says
    // what would let it judge.
    expect(indicatorBadge({ status: 'ok', target_value: 600, judged: false }).label).toBe('No thresholds')
  })

  it('reads an older answer with no flag as it always did', () => {
    expect(indicatorBadge({ status: 'ok', target_value: null }).label).toBe('On track')
    expect(indicatorBadge({ status: 'unknown', target_value: null }).label).toBe('No data')
  })
})
