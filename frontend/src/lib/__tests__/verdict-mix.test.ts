import { describe, expect, it } from 'vitest'

import { verdictMix } from '@/lib/format'

const LABELS = {
  mismatch: 'disagree with the GPS',
  outside: 'outside every area',
  unrecorded: 'with no area recorded',
  match: 'agree',
}

describe('what a grouped pin says about the places under it', () => {
  it('says how many of them actually disagree', () => {
    // The pin is red because one household disagrees. Without this line that
    // reads as all twelve of them.
    expect(verdictMix(12, { mismatch: 1, match: 11 }, LABELS)).toBe(
      '12 locations here - 11 agree, 1 disagree with the GPS',
    )
  })

  it('says nothing for a pin that is one location', () => {
    expect(verdictMix(1, { mismatch: 1 }, LABELS)).toBe('')
    expect(verdictMix(0, undefined, LABELS)).toBe('')
  })

  it('says nothing when there are no verdicts to report', () => {
    expect(verdictMix(9, undefined, LABELS)).toBe('')
    expect(verdictMix(9, {}, LABELS)).toBe('')
    expect(verdictMix(9, { match: 0 }, LABELS)).toBe('')
  })

  it('leads with the commonest, so the pin reads as what is mostly there', () => {
    expect(verdictMix(10, { match: 2, mismatch: 8 }, LABELS)).toBe(
      '10 locations here - 8 disagree with the GPS, 2 agree',
    )
  })
})
