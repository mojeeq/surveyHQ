import { describe, expect, it } from 'vitest'
import { share, summarise, type Countable } from '@/lib/inventory'

const dataset = (over: Partial<Countable> = {}): Countable => ({
  row_count: 100,
  file_size: 1000,
  status: 'ready',
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

describe('summarise', () => {
  it('adds up rows and bytes across the shelf', () => {
    const totals = summarise([
      dataset({ row_count: 1200, file_size: 35_000 }),
      dataset({ row_count: 4593, file_size: 17_000 }),
    ])
    expect(totals.count).toBe(2)
    expect(totals.rows).toBe(5793)
    expect(totals.bytes).toBe(52_000)
  })

  it('counts anything not ready, whatever kind of not ready it is', () => {
    const totals = summarise([
      dataset({ status: 'ready' }),
      dataset({ status: 'processing' }),
      dataset({ status: 'failed' }),
    ])
    expect(totals.unready).toBe(2)
  })

  it('reports the latest touch, not the last one in the list', () => {
    const totals = summarise([
      dataset({ updated_at: '2026-03-04T00:00:00Z' }),
      dataset({ updated_at: '2026-09-30T00:00:00Z' }),
      dataset({ updated_at: '2026-07-11T00:00:00Z' }),
    ])
    expect(totals.updated).toBe('2026-09-30T00:00:00Z')
  })

  it('is empty rather than wrong for an empty shelf', () => {
    expect(summarise([])).toEqual({
      count: 0,
      rows: 0,
      bytes: 0,
      unready: 0,
      updated: null,
    })
  })

  it('treats a still-importing dataset as the zero rows it reports', () => {
    // An import in flight has no row_count yet. The total has to stay a number
    // so the bar still draws; NaN would blank the whole summary.
    const totals = summarise([
      dataset({ row_count: undefined as unknown as number }),
      dataset({ row_count: 50 }),
    ])
    expect(totals.rows).toBe(50)
    expect(Number.isNaN(totals.rows)).toBe(false)
  })
})

describe('share', () => {
  it('gives the fraction of the whole', () => {
    expect(share(25, 100)).toBe(0.25)
  })

  it('is zero, not NaN, when there is nothing to divide by', () => {
    expect(share(0, 0)).toBe(0)
    expect(share(10, 0)).toBe(0)
  })

  it('clamps rather than letting a bar overflow its track', () => {
    expect(share(150, 100)).toBe(1)
    expect(share(-5, 100)).toBe(0)
  })
})
