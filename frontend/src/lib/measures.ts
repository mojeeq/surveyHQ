/**
 * Which variables arithmetic can be done on.
 *
 * Two different questions get confused here, and the platform has words for
 * both. `var_type` is an analytical judgement - what kind of variable is this,
 * a quantity or a code set - and it is a guess, made at import from the shape
 * of the values. `storage_type` is a fact about the file: what the column is
 * actually stored as.
 *
 * The measure picker was asking the first question. It offered only what the
 * importer had decided to call "numeric", and the importer calls any whole
 * number column with few enough distinct values a code set, labels or no
 * labels. Household size, number of children, rooms, years of schooling, age
 * in a small sample: all stored as numbers, all unmeasurable, and the picker
 * said "No variable matches" with the dataset full of numbers.
 *
 * So it asks the second question now. A guess about what a column means should
 * decide what is offered first, not what is possible at all - and nothing is
 * lost by being generous here, because grouping already accepts every variable
 * in the dataset and always has.
 */

import type { Variable } from '@/lib/types'

/**
 * Stored types that hold a number, in both vocabularies that reach us: a
 * pandas dtype for a file read whole, a DuckDB type for one read through
 * Parquet.
 *
 * Matched on the start of the name rather than anywhere in it, which is not
 * fussiness: INTERVAL begins with INT and is not a number, and a search for
 * "int" anywhere would quietly offer the mean of a duration.
 */
const NUMERIC_STORAGE = [
  'int',
  'uint',
  'tinyint',
  'smallint',
  'bigint',
  'hugeint',
  'float',
  'double',
  'real',
  'decimal',
  'numeric',
]

export function storedAsNumber(storage: string | null | undefined): boolean {
  const named = (storage ?? '').trim().toLowerCase()
  if (!named) return false
  if (named.startsWith('interval')) return false
  return NUMERIC_STORAGE.some((one) => named.startsWith(one))
}

/**
 * Whether a mean, a sum or a median of this variable is a thing that can be
 * computed. Not whether it is a sensible thing to compute: averaging a region
 * code is nobody's idea of an answer, but it is the analyst's call to make and
 * not the importer's to prevent.
 */
export function holdsNumbers(variable: Variable): boolean {
  // The judgement is believed when it says numeric, for a dataset ingested
  // before storage types were recorded and whose storage_type is empty.
  if (variable.var_type === 'numeric') return true
  if (variable.var_type === 'datetime' || variable.var_type === 'boolean') return false
  return storedAsNumber(variable.storage_type)
}

/**
 * The measure list: what can be measured, with the ones the importer judged to
 * be quantities first, so the obvious answer is still the first one offered.
 */
export function measurable(variables: readonly Variable[]): Variable[] {
  const offered = variables.filter((one) => !one.is_hidden && holdsNumbers(one))
  return [
    ...offered.filter((one) => one.var_type === 'numeric'),
    ...offered.filter((one) => one.var_type !== 'numeric'),
  ]
}
