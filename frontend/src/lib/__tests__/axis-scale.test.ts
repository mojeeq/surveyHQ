/**
 * Which groupings run along a scale, and so decide their own order.
 *
 * A chart of interviews by day came back in the order the days happened to
 * rank by size: 15 July, 8 July, 9 July, 3 August, 23 July. The query had
 * asked for the biggest first, which is the right default for provinces and
 * meaningless for a timeline - and under a row limit it is worse than
 * meaningless, because the fifty rows kept are a scattered sample of days
 * rather than a stretch of fieldwork.
 *
 * This is the rule the builder uses to leave such a query unsorted, which is
 * what makes the server order it along its own axis. It mirrors the server's
 * own `_reads_as_a_scale`, including the exception for "keep the N largest".
 */
import { describe, expect, it } from 'vitest'

import { scaleOf } from '@/components/explore/shared'
import type { Dimension, Variable } from '@/lib/types'

function variable(name: string, var_type: Variable['var_type']): Variable {
  return {
    id: name,
    name,
    label: name,
    var_type,
    storage_type: 'float64',
    position: 0,
    n_missing: 0,
    n_unique: 0,
    value_labels: {},
    missing_tags: [],
    is_hidden: false,
    min_value: null,
    max_value: null,
    mean_value: null,
  }
}

const day = variable('started', 'datetime')
const age = variable('age', 'numeric')
const province = variable('province', 'categorical')

describe('a grouping that runs along a scale', () => {
  it('is a date variable', () => {
    expect(scaleOf({ variable: 'started' }, day)).toBe('time')
  })

  it('is a date variable grouped by month, quarter or year', () => {
    expect(scaleOf({ variable: 'started', grain: 'month' }, day)).toBe('time')
  })

  it('is any variable the query is grouping by a date part', () => {
    // The grain decides it even where the column was read as text.
    expect(scaleOf({ variable: 'when', grain: 'day' }, undefined)).toBe('time')
  })

  it('is a number, in bands or not', () => {
    expect(scaleOf({ variable: 'age' }, age)).toBe('number')
    expect(scaleOf({ variable: 'age', bin_width: 10 }, age)).toBe('number')
  })
})

describe('a grouping that runs across categories', () => {
  it('is a province', () => {
    expect(scaleOf({ variable: 'province' }, province)).toBeNull()
  })

  it('is a variable the picker has not resolved yet', () => {
    expect(scaleOf({ variable: 'unknown' }, undefined)).toBeNull()
  })

  it('is nothing at all', () => {
    expect(scaleOf(undefined, day)).toBeNull()
  })
})

describe('keeping the N largest', () => {
  it('asks for the ranking, so the axis gives way to it', () => {
    // "The ten busiest days" is a ranking of days, and the fold into "Other"
    // reads the rows in that order.
    const ranked: Dimension = { variable: 'started', limit: 10 }
    expect(scaleOf(ranked, day)).toBeNull()
    expect(scaleOf({ variable: 'age', bin_width: 10, limit: 5 }, age)).toBeNull()
  })
})
