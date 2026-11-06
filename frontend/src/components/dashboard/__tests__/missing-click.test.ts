/**
 * Clicking the category a chart draws for records with no answer.
 *
 * An empty cell is drawn as "-", and the click sent "-" back as a value of
 * the column: a number column refused to compare it and failed every widget
 * on the page, and a text column matched nothing. The click means the records
 * with no answer, and is asked as that.
 */
import { describe, expect, it } from 'vitest'

import { clickTarget, withCrossFilter } from '../filters'

const empty = { op: 'and' as const, conditions: [], groups: [] }

const payload = (rows: unknown[][]) => ({
  grouped_on: ['water'],
  result: {
    columns: [
      { name: 'water', label: 'water', type: 'dimension' as const, data_type: 'numeric' },
      { name: 'count', label: 'Count', type: 'measure' as const, data_type: 'number' },
    ],
    rows,
  },
})

describe('the blank category', () => {
  const withBlanks = payload([
    ['Piped', 4],
    [null, 2],
  ])

  it('resolves to the records with no answer', () => {
    expect(clickTarget(withBlanks, '-')).toEqual({
      variable: 'water',
      value: '-',
      how: { operator: 'missing', valueLabel: 'missing' },
    })
  })

  it('filters the page by "is missing", not by "-"', () => {
    const target = clickTarget(withBlanks, '-')!
    const group = withCrossFilter(empty, {
      variable: target.variable,
      value: target.value,
      label: 'Water',
      from: 'w1',
      ...target.how,
    })
    expect(group.conditions).toEqual([
      { variable: 'water', operator: 'is_null', value: null, use_label: false },
    ])
  })

  it('leaves an answer that really is a dash alone', () => {
    // A text column holding "-" typed in by somebody, and no blanks.
    expect(clickTarget(payload([['-', 3], ['Well', 1]]), '-')).toEqual({
      variable: 'water',
      value: '-',
    })
  })

  it('leaves every other category as a value', () => {
    expect(clickTarget(withBlanks, 'Piped')).toEqual({ variable: 'water', value: 'Piped' })
  })
})
