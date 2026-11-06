import { describe, expect, it } from 'vitest'
import { summarise, type Countable } from '@/lib/inventory'

const dataset = (over: Partial<Countable> = {}): Countable => ({
  file_size: 1000,
  status: 'ready',
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

describe('summarise', () => {
  it('adds up size across the shelf', () => {
    const totals = summarise([
      dataset({ file_size: 35_000 }),
      dataset({ file_size: 17_000 }),
    ])
    expect(totals.count).toBe(2)
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
    expect(summarise([])).toEqual({ count: 0, bytes: 0, unready: 0, waiting: 0, updated: null })
  })

  it('keeps the size a number when a dataset reports none yet', () => {
    // An import in flight has no file_size. The total has to stay a number so
    // the masthead still renders; NaN would blank it.
    const totals = summarise([
      dataset({ file_size: undefined as unknown as number }),
      dataset({ file_size: 50 }),
    ])
    expect(totals.bytes).toBe(50)
    expect(Number.isNaN(totals.bytes)).toBe(false)
  })
})


describe('a dataset emptied on purpose', () => {
  it('is counted as waiting rather than as not ready', () => {
    // Red over a state somebody chose reads as a fault to chase. An emptied
    // dataset is working as intended: its charts are attached and it wants
    // the export uploading again.
    const totals = summarise([
      { file_size: 0, status: 'archived', updated_at: '2026-01-02T00:00:00Z' },
      { file_size: 10, status: 'ready', updated_at: '2026-01-01T00:00:00Z' },
      { file_size: 0, status: 'failed', updated_at: '2026-01-01T00:00:00Z' },
    ])

    expect(totals.waiting).toBe(1)
    expect(totals.unready).toBe(1)
    expect(totals.count).toBe(3)
  })
})
