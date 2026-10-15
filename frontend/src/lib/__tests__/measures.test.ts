import { describe, expect, it } from 'vitest'

import { holdsNumbers, measurable, storedAsNumber } from '@/lib/measures'
import type { Variable } from '@/lib/types'

const variable = (over: Partial<Variable> = {}): Variable =>
  ({
    id: 'v',
    name: 'x',
    label: '',
    var_type: 'numeric',
    storage_type: 'DOUBLE',
    position: 0,
    n_missing: 0,
    n_unique: 10,
    min_value: null,
    max_value: null,
    mean_value: null,
    value_labels: {},
    missing_tags: [],
    is_hidden: false,
    ...over,
  }) as Variable

describe('storedAsNumber', () => {
  it('knows both vocabularies that reach us', () => {
    // A file read whole arrives as a pandas dtype, one read through Parquet as
    // a DuckDB type, and the same column can be described either way.
    for (const stored of [
      'float64',
      'int64',
      'Int64',
      'DOUBLE',
      'BIGINT',
      'INTEGER',
      'DECIMAL(18,3)',
      'REAL',
      'HUGEINT',
      'SMALLINT',
    ]) {
      expect(storedAsNumber(stored), stored).toBe(true)
    }
  })

  it('is not fooled by a type that merely starts the same way', () => {
    // INTERVAL begins with INT and is a duration, not a number. A search for
    // "int" anywhere in the name would offer the mean of one.
    expect(storedAsNumber('INTERVAL')).toBe(false)
    expect(storedAsNumber('VARCHAR')).toBe(false)
    expect(storedAsNumber('object')).toBe(false)
    expect(storedAsNumber('TIMESTAMP')).toBe(false)
    expect(storedAsNumber('')).toBe(false)
    expect(storedAsNumber(null)).toBe(false)
  })
})

describe('holdsNumbers', () => {
  it('offers a coded column that is stored as a number', () => {
    // The whole complaint: the importer called it a code set, so no mean of
    // household size was possible even though every value is a number.
    const householdSize = variable({
      name: 'hh_size',
      var_type: 'categorical',
      storage_type: 'BIGINT',
    })
    expect(holdsNumbers(householdSize)).toBe(true)
  })

  it('believes a judgement of numeric when nothing else is recorded', () => {
    // A dataset ingested before storage types were written carries an empty
    // one, and refusing it would take away measures that used to work.
    expect(holdsNumbers(variable({ storage_type: '' }))).toBe(true)
  })

  it('does not offer text, dates or ticks', () => {
    expect(holdsNumbers(variable({ var_type: 'text', storage_type: 'VARCHAR' }))).toBe(
      false,
    )
    expect(
      holdsNumbers(variable({ var_type: 'datetime', storage_type: 'TIMESTAMP' })),
    ).toBe(false)
    expect(holdsNumbers(variable({ var_type: 'boolean', storage_type: 'BOOLEAN' }))).toBe(
      false,
    )
  })
})

describe('measurable', () => {
  it('puts the obvious quantities first and keeps the rest', () => {
    const list = [
      variable({ name: 'region', var_type: 'categorical', storage_type: 'VARCHAR' }),
      variable({ name: 'hh_size', var_type: 'categorical', storage_type: 'BIGINT' }),
      variable({ name: 'income', var_type: 'numeric', storage_type: 'DOUBLE' }),
    ]

    expect(measurable(list).map((one) => one.name)).toEqual(['income', 'hh_size'])
  })

  it('leaves hidden variables out', () => {
    const list = [
      variable({ name: 'kept' }),
      variable({ name: 'hidden', is_hidden: true }),
    ]

    expect(measurable(list).map((one) => one.name)).toEqual(['kept'])
  })

  it('is empty rather than wrong when nothing can be measured', () => {
    const list = [variable({ name: 'note', var_type: 'text', storage_type: 'VARCHAR' })]

    expect(measurable(list)).toEqual([])
  })
})
