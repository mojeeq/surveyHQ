import { describe, expect, it } from 'vitest'
import { timeLeft } from '@/lib/format'

describe('how long is left on an upload', () => {
  it('says almost done rather than counting the last few seconds', () => {
    // A number that changes faster than it can be read is noise.
    expect(timeLeft(0)).toBe('almost done')
    expect(timeLeft(9.9)).toBe('almost done')
  })

  it('rounds seconds to five, because nobody acts on one', () => {
    expect(timeLeft(12)).toBe('about 10 seconds left')
    expect(timeLeft(43)).toBe('about 45 seconds left')
    expect(timeLeft(89)).toBe('about 90 seconds left')
  })

  it('switches to minutes where seconds stop being readable', () => {
    expect(timeLeft(90)).toBe('about 2 minutes left')
    expect(timeLeft(600)).toBe('about 10 minutes left')
    // The singular matters: "about 1 minutes left" is the sort of thing that
    // makes a platform look unfinished.
    expect(timeLeft(60)).toBe('about 60 seconds left')
    expect(timeLeft(95)).toBe('about 2 minutes left')
    expect(timeLeft(70 * 60)).toBe('about 1h 10m left')
  })

  it('handles the hours a census export on a field connection really takes', () => {
    expect(timeLeft(3600)).toBe('about 1h 00m left')
    expect(timeLeft(3600 * 2 + 60 * 5)).toBe('about 2h 05m left')
  })

  it('says nothing rather than something absurd when there is no estimate', () => {
    // rate is zero before the first chunk, and Infinity divided by it follows.
    expect(timeLeft(Infinity)).toBe('')
    expect(timeLeft(NaN)).toBe('')
    expect(timeLeft(-1)).toBe('')
  })
})
