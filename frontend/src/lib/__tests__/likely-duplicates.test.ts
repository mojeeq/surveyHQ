/**
 * How a likely-duplicates check's form starts, and what it says it will do.
 */
import { describe as group, expect, it } from 'vitest'

import { describe, guessField } from '@/lib/likely-duplicates'
import type { Variable } from '@/lib/types'

const variable = (name: string, extra: Partial<Variable> = {}): Variable =>
  ({ name, label: '', value_labels: {}, var_type: 'categorical', n_unique: 3, ...extra }) as Variable

group('the comparison a chosen variable starts with', () => {
  it('compares a name by spelling, at double weight', () => {
    expect(guessField(variable('first_name', { var_type: 'text' }))).toEqual({
      variable: 'first_name',
      compare: 'text',
      weight: 2,
    })
    // A column of many different values with no labels is free text too.
    expect(guessField(variable('surname', { n_unique: 400 })).compare).toBe('text')
  })

  it('compares an age within a year, and other numbers exactly', () => {
    expect(guessField(variable('age', { var_type: 'numeric' }))).toMatchObject({
      compare: 'number',
      tolerance: 1,
    })
    expect(guessField(variable('hh_size', { var_type: 'numeric' }))).toMatchObject({
      compare: 'number',
      tolerance: 0,
    })
  })

  it('compares a date of birth as a date, however it is stored', () => {
    expect(guessField(variable('dob', { var_type: 'text' })).compare).toBe('date')
    expect(guessField(variable('visit', { var_type: 'datetime' })).compare).toBe('date')
  })

  it('compares a code exactly', () => {
    expect(guessField(variable('sex', { value_labels: { '1': 'Male', '2': 'Female' } })).compare).toBe(
      'exact',
    )
  })
})

group('what the form says it will do', () => {
  it('asks for two fields until it has them', () => {
    expect(describe({ fields: [{ variable: 'name', compare: 'text' }] })).toMatch(/at least two fields/)
  })

  it('names the fields, the similarity and the grouping', () => {
    expect(
      describe({
        fields: [
          { variable: 'name', compare: 'text' },
          { variable: 'age', compare: 'number', tolerance: 1 },
        ],
        block: [
          { variable: 'ea', how: 'same' },
          { variable: 'surname', how: 'first_letter' },
        ],
        min_similarity: 0.85,
      }),
    ).toBe('Flags pairs of records at least 85% alike on name, age within the same ea and first letter of surname.')
  })
})

group('a name told by what it is called', () => {
  it('compares a first name by spelling even when it has few values', () => {
    expect(guessField(variable('first_name', { n_unique: 12 })).compare).toBe('text')
    expect(guessField(variable('Surname', { n_unique: 8 })).compare).toBe('text')
  })

  it('names a field joined from parts by its parts', () => {
    expect(
      describe({
        fields: [
          { variable: 'first_name', also: ['surname'], compare: 'text' },
          { variable: 'age', compare: 'number' },
        ],
      }),
    ).toBe('Flags pairs of records at least 90% alike on first_name + surname, age.')
  })
})
