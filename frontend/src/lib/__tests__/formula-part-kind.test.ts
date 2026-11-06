/**
 * Which kind of count a formula's part is, read back off the part.
 *
 * The select holds no state of its own: it shows what the part says it is, so
 * choosing an option has to survive the round trip through the part and back.
 * It did not. Everything but "Records" needs a variable, choosing one left the
 * variable unchosen, and "unchosen" was being read as "this measure has no
 * variable" - so every option snapped back to "Records" and a part could only
 * ever be a row count.
 *
 * So a variable of null means the measure takes none, and an empty one means
 * it takes one that has not been picked yet. The two are different states and
 * the difference is the whole bug.
 */
import { describe, expect, it } from 'vitest'
import { PART_MEASURES, kindOf, measureFor } from '@/components/monitoring/FormulaBuilder'

const part = (measure: { agg: string; variable: string | null }) => ({
  name: 'part_1',
  measure: measure as { agg: 'count'; variable: string | null },
  filters: { op: 'and' as const, conditions: [], groups: [] },
})

describe('choosing what a part counts', () => {
  it('survives being read back, for every kind on offer', () => {
    for (const one of PART_MEASURES) {
      expect(kindOf(part(measureFor(one.value)))).toBe(one.value)
    }
  })

  it('still reads back once a variable has been chosen', () => {
    expect(kindOf(part({ agg: 'sum', variable: 'minutes' }))).toBe('sum')
    expect(kindOf(part({ agg: 'count', variable: 'status' }))).toBe('answered')
  })

  it('tells a measure with no variable from one whose variable is unchosen', () => {
    expect(kindOf(part({ agg: 'count', variable: null }))).toBe('records')
    expect(kindOf(part({ agg: 'count', variable: '' }))).toBe('answered')
  })

  it('asks for no variable where the count needs none', () => {
    expect(measureFor('records').variable).toBeNull()
    expect(measureFor('sum').variable).toBe('')
  })

  it('falls back to counting records for a measure it does not know', () => {
    expect(kindOf(part({ agg: 'p90', variable: 'age' }))).toBe('records')
  })
})
