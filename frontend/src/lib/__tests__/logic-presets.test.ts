/**
 * The preset that replaced the Cross-variable consistency check type.
 *
 * It has to land on a condition the server will actually run, because the
 * button looks like it worked either way: a row naming a variable that is not
 * in the dataset, or comparing against a literal when it meant a column, only
 * shows up when the check is run.
 */
import { describe, expect, it } from 'vitest'

import { COLUMN_OPERATORS } from '@/components/FilterBuilder'
import { firstPair, LOGIC_PRESETS } from '@/lib/logic-presets'
import type { Variable } from '@/lib/types'

const vars = (...spec: [string, string][]) =>
  spec.map(([name, var_type]) => ({ name, var_type, label: name })) as unknown as Variable[]

// The real vocabulary, from ingest.classify: boolean, datetime, numeric,
// categorical, text. Worth stating, because an earlier version of this test
// used "string", which does not exist, and so proved nothing about any
// dataset the platform can actually produce.
const dataset = vars(
  ['interview__key', 'text'],
  ['region', 'categorical'],
  ['age', 'numeric'],
  ['income', 'numeric'],
)

const consistency = LOGIC_PRESETS.find((p) => p.id === 'consistency')!

describe('the cross-variable consistency preset', () => {
  it('builds one row comparing two columns, not a literal', () => {
    const built = consistency.build(dataset)
    expect(built.conditions).toHaveLength(1)
    const [row] = built.conditions
    expect(row.other_variable).toBe('income')
    expect(row.variable).toBe('age')
    // A literal left behind would be the stale right hand side the builder
    // goes to lengths to avoid.
    expect(row.value).toBe('')
  })

  it('opens in the direction the retired check read', () => {
    // It asked for the relationship that must hold and counted the breaks.
    expect(consistency.flag).toBe('no_match')
  })

  it('uses an operator the server accepts between two columns', () => {
    expect(COLUMN_OPERATORS).toContain(consistency.build(dataset).conditions[0].operator)
  })

  it('names variables the dataset actually has', () => {
    const names = dataset.map((v) => v.name)
    const [row] = consistency.build(dataset).conditions
    expect(names).toContain(row.variable)
    expect(names).toContain(row.other_variable)
  })
})

describe('choosing the pair to start on', () => {
  it('prefers two numerics over the columns that happen to come first', () => {
    expect(firstPair(dataset)).toEqual(['age', 'income'])
  })

  it('prefers two dates over two numbers', () => {
    // A start and an end are the classic pairwise rule, and the one the form
    // offers as its example.
    const withDates = vars(
      ['age', 'numeric'],
      ['income', 'numeric'],
      ['start_time', 'datetime'],
      ['end_time', 'datetime'],
    )
    expect(firstPair(withDates)).toEqual(['start_time', 'end_time'])
  })

  it('will not pair a date with a number', () => {
    const one = vars(['age', 'numeric'], ['end_time', 'datetime'], ['b', 'numeric'])
    // Two numerics exist, a lone date does not make a pair.
    expect(firstPair(one)).toEqual(['age', 'b'])
  })

  it('leaves answer codes out of the guess', () => {
    // Two categoricals sort fine, but "sex at most region" is a worse opening
    // guess than the first two of anything. The text pair comes first so the
    // fallback and a categorical preference give different answers - put the
    // codes first and both produce them, and the test proves nothing.
    const coded = vars(
      ['key', 'text'],
      ['note', 'text'],
      ['sex', 'categorical'],
      ['region', 'categorical'],
    )
    expect(firstPair(coded)).toEqual(['key', 'note'])
  })

  it('falls back to whatever there is when no orderable pair exists', () => {
    expect(firstPair(vars(['a', 'text'], ['b', 'text'], ['c', 'numeric']))).toEqual([
      'a',
      'b',
    ])
  })

  it('repeats the one variable rather than leaving a select empty', () => {
    // Useless as a rule and obviously so, which beats a row that silently
    // will not save.
    expect(firstPair(vars(['only', 'numeric']))).toEqual(['only', 'only'])
  })

  it('survives a dataset with no variables at all', () => {
    expect(firstPair([])).toEqual(['', ''])
  })
})
