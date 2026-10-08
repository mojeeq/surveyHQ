/**
 * Moving a condition between a literal and another column.
 *
 * The risk is a stale right hand side: a row still carrying `value` while it
 * compares against a column, or still carrying `other_variable` after being
 * switched back. Either sends the server something other than what the form
 * shows, and the form looks perfectly correct in both cases.
 */
import { describe, expect, it } from 'vitest'

import { COLUMN_OPERATORS, sideSwitch } from '@/components/FilterBuilder'
import type { Condition, Variable } from '@/lib/types'

const variables = [
  { name: 'age', label: 'Age', var_type: 'numeric' },
  { name: 'income', label: 'Income', var_type: 'numeric' },
] as unknown as Variable[]

const base: Condition = { variable: 'age', operator: 'lt', value: '25', use_label: false }

describe('switching which side a condition compares against', () => {
  it('drops the literal when it moves to a column', () => {
    const patch = sideSwitch(base, true, variables)
    expect(patch.value).toBe('')
    expect(patch.use_label).toBe(false)
    expect(patch.other_variable).toBe('income')
  })

  it('drops the column when it moves back to a literal', () => {
    const patch = sideSwitch({ ...base, other_variable: 'income' }, false, variables)
    expect(patch.other_variable).toBeNull()
  })

  it('keeps an operator that still means something between two columns', () => {
    expect(sideSwitch({ ...base, operator: 'gte' }, true, variables).operator).toBe('gte')
  })

  it('falls back to equals from an operator a column cannot answer', () => {
    for (const operator of ['contains', 'in', 'between', 'starts_with'] as const) {
      expect(sideSwitch({ ...base, operator }, true, variables).operator).toBe('eq')
    }
  })

  it('offers a different variable than the one on the left, where there is one', () => {
    expect(sideSwitch({ ...base, variable: 'income' }, true, variables).other_variable).toBe(
      'age',
    )
  })

  it('falls back to the same variable when the dataset has only one', () => {
    const only = [variables[0]]
    expect(sideSwitch(base, true, only).other_variable).toBe('age')
  })

  it('leaves a column already chosen alone', () => {
    const patch = sideSwitch({ ...base, other_variable: 'income' }, true, variables)
    expect(patch.other_variable).toBe('income')
  })

  it('offers exactly the operators the server will accept', () => {
    // SQLBuilder.COLUMN_COMPARISONS refuses anything else, so a list that
    // drifts wider here means a form that builds a rule the server declines.
    expect([...COLUMN_OPERATORS].sort()).toEqual(['eq', 'gt', 'gte', 'lt', 'lte', 'ne'])
  })
})
