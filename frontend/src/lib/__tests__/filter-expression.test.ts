/**
 * A filter written as an expression reads into the builder's own filter, and
 * a saved filter prints back as the expression.
 */
import { describe, expect, it } from 'vitest'

import { parseFilter, printFilter, suggestAt } from '@/lib/filter-expression'
import type { FilterGroup, Variable } from '@/lib/types'

const variable = (name: string, extra: Partial<Variable> = {}): Variable =>
  ({ name, label: '', value_labels: {}, var_type: 'numeric', ...extra }) as Variable

const variables = [
  variable('age'),
  variable('sex', { value_labels: { '1': 'Male', '2': 'Female' } }),
  variable('district', { label: 'District', value_labels: { '1': 'North', '2': 'East', '3': 'West' } }),
  variable('interview__key', { var_type: 'text' }),
  variable('start_date', { var_type: 'datetime' }),
  variable('end_date', { var_type: 'datetime' }),
  variable('phone'),
  variable('inc2019'),
  variable('inc2020'),
  variable('total'),
  variable('boys'),
  variable('girls'),
  variable('water__3', { label: 'Rain water' }),
  variable('my column', { var_type: 'text' }),
]

const read = (text: string): FilterGroup => {
  const result = parseFilter(text, variables)
  if (!result.ok) throw new Error(`${result.error.message} at ${result.error.from}`)
  return result.filter
}

const fails = (text: string) => {
  const result = parseFilter(text, variables)
  if (result.ok) throw new Error(`"${text}" was read as ${JSON.stringify(result.filter)}`)
  return result.error
}

describe('reading an expression', () => {
  it('reads a run of && as one group', () => {
    expect(read('age >= 15 && age < 50 && sex == 2')).toEqual({
      op: 'and',
      conditions: [
        { variable: 'age', operator: 'gte', value: '15', use_label: false },
        { variable: 'age', operator: 'lt', value: '50', use_label: false },
        { variable: 'sex', operator: 'eq', value: '2', use_label: false },
      ],
      groups: [],
    })
  })

  it('makes a bracket of a different kind a group of its own', () => {
    expect(read('age >= 15 && (district == 1 || district == 2)')).toEqual({
      op: 'and',
      conditions: [{ variable: 'age', operator: 'gte', value: '15', use_label: false }],
      groups: [
        {
          op: 'or',
          conditions: [
            { variable: 'district', operator: 'eq', value: '1', use_label: false },
            { variable: 'district', operator: 'eq', value: '2', use_label: false },
          ],
          groups: [],
        },
      ],
    })
  })

  it('binds && tighter than ||, as C# does', () => {
    const filter = read('sex == 1 || sex == 2 && age > 15')
    expect(filter.op).toBe('or')
    expect(filter.conditions).toHaveLength(1)
    expect(filter.groups[0].op).toBe('and')
    expect(filter.groups[0].conditions).toHaveLength(2)
  })

  it('takes a label for its code', () => {
    expect(read('sex == "Female"').conditions[0].value).toBe('2')
    expect(read('district != "west"').conditions[0]).toMatchObject({ operator: 'ne', value: '3' })
    expect(read('district.InList("North", 2)').conditions[0]).toMatchObject({ operator: 'in', value: ['1', '2'] })
  })

  it('reads the Survey Solutions helpers', () => {
    const [inRange, contains, answered, ticked] = read(
      'age.InRange(15, 49) && interview__key.StartsWith("ab") && IsAnswered(phone) && IsSelected(water__3)',
    ).conditions
    expect(inRange).toMatchObject({ operator: 'between', value: ['15', '49'] })
    expect(contains).toMatchObject({ operator: 'starts_with', value: 'ab' })
    expect(answered).toMatchObject({ variable: 'phone', operator: 'is_not_null' })
    expect(ticked).toMatchObject({ variable: 'water__3', operator: 'selected' })
  })

  it('pushes ! down to the conditions', () => {
    expect(read('!IsAnswered(phone)').conditions[0].operator).toBe('is_null')
    expect(read('!(age > 15 && sex == 1)')).toEqual({
      op: 'or',
      conditions: [
        { variable: 'age', operator: 'lte', value: '15', use_label: false },
        { variable: 'sex', operator: 'ne', value: '1', use_label: false },
      ],
      groups: [],
    })
    expect(read('!age.InRange(15, 49)')).toMatchObject({
      op: 'or',
      conditions: [
        { operator: 'lt', value: '15' },
        { operator: 'gt', value: '49' },
      ],
    })
  })

  it('compares one column with another', () => {
    expect(read('end_date < start_date').conditions[0]).toEqual({
      variable: 'end_date',
      operator: 'lt',
      value: '',
      use_label: false,
      other_variable: 'start_date',
    })
  })

  it('reads a value on the left the other way round, and null as missing', () => {
    expect(read('15 <= age').conditions[0]).toMatchObject({ variable: 'age', operator: 'gte', value: '15' })
    expect(read('phone == null').conditions[0].operator).toBe('is_null')
    expect(read('phone != null').conditions[0].operator).toBe('is_not_null')
  })

  it('takes the words and/or/not, = for ==, and a name in backticks', () => {
    expect(read('age > 15 and not (sex = 1)')).toMatchObject({
      op: 'and',
      conditions: [{ operator: 'gt' }, { operator: 'ne', variable: 'sex' }],
    })
    expect(read('`my column`.Contains("x")').conditions[0].variable).toBe('my column')
    expect(read('AGE > -2').conditions[0]).toMatchObject({ variable: 'age', value: '-2' })
  })

  it('is the empty filter when blank', () => {
    expect(read('   ')).toEqual({ op: 'and', conditions: [], groups: [] })
  })
})

describe('saying what is wrong, and where', () => {
  it('names a mistyped variable and the one it is probably', () => {
    const error = fails('dstrict == 1')
    expect(error.message).toBe('There is no variable "dstrict" - did you mean district?')
    expect([error.from, error.to]).toEqual([0, 7])
  })

  it('names a label that is not there, and the nearest that is', () => {
    expect(fails('district == "Noth"').message).toBe(
      'district has no label "Noth" - did you mean "North"?',
    )
  })

  it('asks for quotes round text written bare', () => {
    expect(fails('interview__key == abc').message).toContain('put it in quotes: "abc"')
  })

  it('catches single & and |, unclosed brackets and strings, and what is left over', () => {
    expect(fails('age > 1 & sex == 1').message).toBe('Write &&, not a single &')
    expect(fails('(age > 1').message).toBe('Expected a closing ) at the end')
    expect(fails('sex == "Male').message).toBe('This text has no closing "')
    expect(fails('age > 1 sex == 1').message).toBe('Expected && or || before this')
    expect(fails('age.InRange(1)').message).toBe('InRange takes two values, the lowest and the highest')
    expect(fails('age').message).toBe('Expected a comparison after age, such as == or >')
  })
})

describe('printing a saved filter', () => {
  it('writes codes as their labels, and brackets only where they are needed', () => {
    const filter: FilterGroup = {
      op: 'and',
      conditions: [
        { variable: 'age', operator: 'between', value: ['15', '49'] },
        { variable: 'sex', operator: 'eq', value: '2' },
      ],
      groups: [
        {
          op: 'or',
          conditions: [
            { variable: 'district', operator: 'in', value: ['1', '3'] },
            { variable: 'phone', operator: 'is_null', value: null },
          ],
          groups: [],
        },
        { op: 'or', conditions: [{ variable: 'water__3', operator: 'selected', value: null }], groups: [] },
      ],
    }
    expect(printFilter(filter, variables)).toBe(
      'age.InRange(15, 49) && sex == "Female" && (district.InList("North", "West") || !IsAnswered(phone)) && IsSelected(water__3)',
    )
  })

  it('reads back as the same filter', () => {
    const texts = [
      // A group keeps its plain conditions ahead of its brackets, so that is
      // the order an expression comes back in.
      'age >= 15 && !IsAnswered(phone) && (district == "East" || district == "West")',
      'end_date < start_date || interview__key.Contains("x\\"y")',
      '`my column`.EndsWith("z") && start_date.OnOrAfter("2026-01-01") && start_date.Before("2026-02-01")',
      '!district.InList("North") && !interview__key.Contains("test")',
    ]
    for (const text of texts) {
      const filter = read(text)
      expect(printFilter(filter, variables)).toBe(text)
      expect(read(printFilter(filter, variables))).toEqual(filter)
    }
  })

  it('writes a row left half-filled in the builder so that it still reads', () => {
    const filter: FilterGroup = {
      op: 'and',
      conditions: [
        { variable: 'interview__key', operator: 'eq', value: '' },
        { variable: 'sex', operator: 'eq', value: '' },
      ],
      groups: [],
    }
    const text = printFilter(filter, variables)
    expect(text).toBe('interview__key == "" && sex == ""')
    expect(read(text).conditions.map((one) => one.value)).toEqual(['', ''])
  })
})

describe('suggesting what comes next', () => {
  it('offers the variables while a name is being typed', () => {
    const found = suggestAt('age > 1 && dis', 14, variables)
    expect(found?.from).toBe(11)
    expect(found?.options.map((one) => one.label)).toContain('district')
  })

  it('offers the methods after a dot', () => {
    const found = suggestAt('age.In', 6, variables)
    expect(found?.from).toBe(4)
    expect(found?.options.map((one) => one.label)).toEqual(
      expect.arrayContaining(['InList', 'InRange', 'Contains']),
    )
  })

  it('offers a coded variable\'s labels inside the quotes', () => {
    expect(suggestAt('district == "', 13, variables)?.options.map((one) => one.label)).toEqual([
      'North',
      'East',
      'West',
    ])
    const text = 'district.InList("North", "'
    expect(suggestAt(text, text.length, variables)?.options[0].label).toBe('North')
  })
})

describe('arithmetic', () => {
  it('keeps a sum on the left and a number on the right', () => {
    expect(read('inc2020 - inc2019 > 100').conditions[0]).toEqual({
      variable: 'inc2020',
      operator: 'gt',
      value: '100',
      use_label: false,
      formula: 'inc2020 - inc2019',
    })
  })

  it('keeps a sum on the right as the other side', () => {
    expect(read('total != boys + girls').conditions[0]).toEqual({
      variable: 'total',
      operator: 'ne',
      value: '',
      use_label: false,
      other_formula: 'boys + girls',
    })
    expect(read('boys * 2 < total').conditions[0]).toMatchObject({
      formula: 'boys * 2',
      other_variable: 'total',
    })
  })

  it('reads * and / before + and -, and keeps the brackets that matter', () => {
    expect(read('(inc2020 - inc2019) / inc2019 * 100 >= 10').conditions[0].formula).toBe(
      '(inc2020 - inc2019) / inc2019 * 100',
    )
    expect(read('total - (boys - girls) > 0').conditions[0].formula).toBe('total - (boys - girls)')
    expect(read('total - boys - girls > 0').conditions[0].formula).toBe('total - boys - girls')
    expect(read('-inc2019 + inc2020 > 0').conditions[0].formula).toBe('-inc2019 + inc2020')
  })

  it('tells a bracketed sum from a bracketed group', () => {
    expect(read('(inc2020 - inc2019) > 100 && (sex == 1 || sex == 2)')).toMatchObject({
      op: 'and',
      conditions: [{ formula: 'inc2020 - inc2019', operator: 'gt' }],
      groups: [{ op: 'or' }],
    })
    expect(read('((boys + girls)) * 2 == total').conditions[0].formula).toBe('(boys + girls) * 2')
  })

  it('turns round a sum written on the right of a number', () => {
    expect(read('100 < inc2020 - inc2019').conditions[0]).toMatchObject({
      formula: 'inc2020 - inc2019',
      operator: 'gt',
      value: '100',
    })
    expect(read('age > 60 * 2').conditions[0]).toMatchObject({ variable: 'age', value: '120' })
  })

  it('pushes ! through a sum like any comparison', () => {
    expect(read('!(inc2020 - inc2019 > 100)').conditions[0]).toMatchObject({
      formula: 'inc2020 - inc2019',
      operator: 'lte',
    })
  })

  it('says what cannot be done with one', () => {
    expect(fails('inc2020 - inc2019 > "a lot"').message).toBe('A sum is compared with a number')
    expect(fails('inc2020 + "x" > 1').message).toBe('A sum works on numbers - text cannot be part of one')
    expect(fails('2 + 2 > 3').message).toBe('Neither side names a variable')
    expect(fails('`my column` * 2 > 1').message).toContain('only names that are plain words')
    expect(fails('inc2020 - inc2019 == null').message).toBe('Only a variable can be compared with null')
    expect(fails('inc2020 - > 1').message).toBe('Expected a value here')
  })

  it('prints back as written', () => {
    for (const text of [
      'inc2020 - inc2019 > 100',
      'total != boys + girls',
      '(inc2020 - inc2019) / inc2019 * 100 >= 10 && !IsAnswered(phone)',
      'boys * 2 < total',
    ]) {
      expect(printFilter(read(text), variables)).toBe(text)
    }
  })
})
