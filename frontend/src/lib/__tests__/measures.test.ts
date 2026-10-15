import { describe, expect, it } from 'vitest'

import { filterableVariables } from '@/components/DashboardFilters'
import { holdsNumbers, measurable, storedAsNumber } from '@/lib/measures'
import type { Dataset, Variable } from '@/lib/types'

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

describe('filterableVariables', () => {
  // The dashboard's add-filter list asked for the importer's judgement, which
  // was a proxy for "few enough values to pick from" and stopped holding the
  // moment an unlabelled 1/2/3 code started reading as a quantity. On reimport
  // every one of them left the list, though three values fit a dropdown as
  // well as they ever did.
  const dataset = (variables: Partial<Variable>[]) =>
    ({ variables: variables.map((one) => variable(one)) }) as Dataset

  it('offers a code with no names for its codes', () => {
    const list = filterableVariables(
      dataset([{ name: 'region', var_type: 'numeric', storage_type: 'BIGINT', n_unique: 3 }]),
    )
    expect(list.map((one) => one.name)).toEqual(['region'])
  })

  it('still offers a named code set', () => {
    const list = filterableVariables(
      dataset([{ name: 'sex', var_type: 'categorical', n_unique: 2 }]),
    )
    expect(list.map((one) => one.name)).toEqual(['sex'])
  })

  it('leaves out what will not fit in a list', () => {
    // An identifier with a value per row, which is what the cap is for.
    const list = filterableVariables(
      dataset([{ name: 'interview__key', var_type: 'text', n_unique: 20000 }]),
    )
    expect(list).toEqual([])
  })

  it('leaves out dates, which want a range rather than ticks', () => {
    const list = filterableVariables(
      dataset([{ name: 'visited_at', var_type: 'datetime', n_unique: 40 }]),
    )
    expect(list).toEqual([])
  })

  it('leaves out hidden variables', () => {
    const list = filterableVariables(
      dataset([{ name: 'gone', var_type: 'categorical', n_unique: 3, is_hidden: true }]),
    )
    expect(list).toEqual([])
  })

  it('is empty rather than wrong without a dataset', () => {
    expect(filterableVariables(undefined)).toEqual([])
  })
})
