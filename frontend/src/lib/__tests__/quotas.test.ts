/**
 * The per-group quotas, added up and compared with the headline.
 *
 * The headline target of a broken-down indicator is what the group quotas add
 * up to. Nothing enforces that - a survey may watch quotas in four districts
 * out of forty - but a form with sixty number boxes is where a digit goes
 * missing, and this is the only place that would ever say so.
 */
import { describe, expect, it } from 'vitest'
import { quotaSummary } from '@/lib/quotas'

describe('quotaSummary', () => {
  it('says nothing is set when nothing is set', () => {
    expect(quotaSummary({}, '15040')).toMatchObject({ set: 0, total: 0, difference: -15040 })
    expect(quotaSummary({ '0508': '', '0102': undefined }, '100')).toMatchObject({ set: 0 })
  })

  it('counts and adds only the groups that carry a quota', () => {
    const summary = quotaSummary({ '0508': '346', '0102': '437', '0902': '' }, '1000')

    expect(summary.set).toBe(2)
    expect(summary.total).toBe(783)
  })

  it('reports the gap to the headline, the way the form reads it', () => {
    expect(quotaSummary({ a: '400', b: '600' }, '1000').difference).toBe(0)
    expect(quotaSummary({ a: '400', b: '380' }, '1000').difference).toBe(-220)
    expect(quotaSummary({ a: '700', b: '600' }, '1000').difference).toBe(300)
  })

  it('does not report a gap of a billionth', () => {
    // A sum of decimals lands on 14999.999999999998, and "0.000000000002
    // short of the target" is worse than saying nothing.
    const summary = quotaSummary({ a: '0.1', b: '0.2' }, '0.3')

    expect(summary.difference).toBe(0)
  })

  it('has no gap to report when there is no headline', () => {
    expect(quotaSummary({ a: '400' }, '')).toMatchObject({ total: 400, headline: null, difference: null })
  })

  it('ignores what is not a number, as the box can hold anything typed', () => {
    const summary = quotaSummary({ a: '400', b: 'twelve', c: '  ' }, '400')

    expect(summary.set).toBe(1)
    expect(summary.total).toBe(400)
    expect(summary.difference).toBe(0)
  })

  it('takes numbers as readily as the strings the form holds', () => {
    expect(quotaSummary({ a: 400, b: 600 }, 1000)).toMatchObject({ set: 2, total: 1000, difference: 0 })
  })
})
