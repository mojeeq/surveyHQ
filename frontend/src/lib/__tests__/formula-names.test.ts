/**
 * The names a formula's parts are given.
 *
 * A part is referred to by name inside the formula, so the name has to be
 * something a formula can contain: the server refuses anything else, and the
 * place to find that out is the box it is typed in, not the save button.
 */
import { describe, expect, it } from 'vitest'
import { freeName, tidyName } from '@/components/monitoring/FormulaBuilder'

describe('tidyName', () => {
  it('leaves a name a formula can use alone', () => {
    expect(tidyName('done')).toBe('done')
    expect(tidyName('interviews_done')).toBe('interviews_done')
    expect(tidyName('part_2')).toBe('part_2')
  })

  it('turns a space into something the formula can refer to', () => {
    // Otherwise "interviews done / issued" is two names and a mistake.
    expect(tidyName('interviews done')).toBe('interviews_done')
  })

  it('refuses the characters that mean something in a formula', () => {
    expect(tidyName('done-issued')).toBe('done_issued')
    expect(tidyName('done/issued')).toBe('done_issued')
    expect(tidyName('done (all)')).toBe('done__all_')
  })

  it('does not let a name start with a digit', () => {
    // 1st would read as the number 1 followed by a name.
    expect(tidyName('1st')).toBe('_st')
  })
})

describe('freeName', () => {
  const part = (name: string) => ({
    name,
    measure: { agg: 'count' as const, variable: null },
    filters: { op: 'and' as const, conditions: [], groups: [] },
  })

  it('starts at the first one', () => {
    expect(freeName([])).toBe('part_1')
  })

  it('skips the ones already taken', () => {
    expect(freeName([part('part_1'), part('part_2')])).toBe('part_3')
  })

  it('fills a gap rather than counting past it', () => {
    expect(freeName([part('part_1'), part('part_3')])).toBe('part_2')
  })

  it('is not confused by names somebody chose', () => {
    expect(freeName([part('done'), part('issued')])).toBe('part_1')
  })
})
