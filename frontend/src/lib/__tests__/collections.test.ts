/**
 * How a list page narrows and orders what it shows.
 *
 * Two pages share these rules, which is the reason they are here rather than
 * in either page: a search box that behaves one way on Projects and another on
 * Dashboards is a bug nobody reports clearly, because the person reporting it
 * only uses one of the two.
 */

import { describe, expect, it } from 'vitest'

import { arrange, by, matches } from '@/lib/collections'

describe('what the search box finds', () => {
  it('finds a word anywhere in any field', () => {
    expect(matches('census', ['Palau Census 2025', 'Field work'])).toBe(true)
    expect(matches('field', ['Palau Census 2025', 'Field work'])).toBe(true)
  })

  it('ignores case', () => {
    expect(matches('PALAU', ['Palau Census 2025'])).toBe(true)
    expect(matches('palau', ['PALAU CENSUS'])).toBe(true)
  })

  it('needs every word, but not all in one field', () => {
    // Somebody types what they remember, not what is in one column.
    expect(matches('palau 2025', ['Palau Census', '2025 round'])).toBe(true)
    expect(matches('palau fiji', ['Palau Census', '2025 round'])).toBe(false)
  })

  it('matches everything when nothing is typed', () => {
    expect(matches('', ['anything'])).toBe(true)
    expect(matches('   ', ['anything'])).toBe(true)
  })

  it('does not trip over a field that is missing', () => {
    // A project with no description, a dashboard with no project.
    expect(matches('palau', ['Palau Census', null, undefined])).toBe(true)
    expect(matches('palau', [null, undefined])).toBe(false)
  })

  it('never matches a missing field on the word for it', () => {
    // A missing field is dropped rather than stringified. Keeping it would
    // put "null" and "undefined" in the haystack, and then "un" - a real
    // prefix somebody types - would find every row with a blank description.
    expect(matches('un', ['Palau Census', undefined])).toBe(false)
    expect(matches('null', ['Palau Census', null])).toBe(false)
    expect(matches('undefined', [undefined])).toBe(false)
  })

  it('searches numbers as written', () => {
    expect(matches('12', ['Round two', 12])).toBe(true)
  })

  it('treats extra spaces between words as one', () => {
    expect(matches('palau   census', ['Palau Census 2025'])).toBe(true)
  })
})

describe('how the order is decided', () => {
  const rows = [
    { name: 'Vanuatu LFS', widgets: 5 },
    { name: 'Fiji Census', widgets: 12 },
    { name: 'palau census', widgets: 9 },
  ]

  it('orders text the way a person reads it, ignoring case', () => {
    const sorted = [...rows].sort(by((r) => r.name))
    expect(sorted.map((r) => r.name)).toEqual(['Fiji Census', 'palau census', 'Vanuatu LFS'])
  })

  it('orders numbers by size, not as text', () => {
    // Sorted as text, 12 would come before 5.
    const sorted = [...rows].sort(by((r) => r.widgets))
    expect(sorted.map((r) => r.widgets)).toEqual([5, 9, 12])
  })

  it('orders negative and fractional numbers correctly', () => {
    // Text collation gets these wrong even with numeric awareness on: the
    // minus reads as a separator, and 1.25 against 1.5 compares digit by
    // digit. This is why numbers are compared as numbers first.
    const rates = [{ v: 1.5 }, { v: -2 }, { v: 1.25 }, { v: 0 }]
    expect([...rates].sort(by((r) => r.v)).map((r) => r.v)).toEqual([-2, 0, 1.25, 1.5])
  })

  it('reverses when asked', () => {
    const sorted = [...rows].sort(by((r) => r.widgets, 'desc'))
    expect(sorted.map((r) => r.widgets)).toEqual([12, 9, 5])
  })

  it('reads a number inside a name as a number', () => {
    // "Round 10" after "Round 2", which plain text comparison gets backwards.
    const named = [{ name: 'Round 10' }, { name: 'Round 2' }]
    expect([...named].sort(by((r) => r.name)).map((r) => r.name)).toEqual([
      'Round 2',
      'Round 10',
    ])
  })

  it('sorts dates correctly as the strings the API sends', () => {
    const stamps = [
      { at: '2026-02-09T10:00:00Z' },
      { at: '2026-02-10T09:00:00Z' },
      { at: '2026-01-31T23:00:00Z' },
    ]
    expect([...stamps].sort(by((s) => s.at, 'desc')).map((s) => s.at)).toEqual([
      '2026-02-10T09:00:00Z',
      '2026-02-09T10:00:00Z',
      '2026-01-31T23:00:00Z',
    ])
  })
})

describe('rows with nothing to order by', () => {
  const rows = [
    { name: 'Has one', note: 'beta' },
    { name: 'Blank', note: '' },
    { name: 'Missing', note: null as string | null },
    { name: 'Also one', note: 'alpha' },
  ]

  it('puts them last ascending', () => {
    expect([...rows].sort(by((r) => r.note)).map((r) => r.name)).toEqual([
      'Also one',
      'Has one',
      'Blank',
      'Missing',
    ])
  })

  it('still puts them last descending', () => {
    // The point of the whole function. Reversing the order must not float the
    // empty rows to the top, or the list opens looking broken.
    expect([...rows].sort(by((r) => r.note, 'desc')).map((r) => r.name)).toEqual([
      'Has one',
      'Also one',
      'Blank',
      'Missing',
    ])
  })

  it('treats a count of zero as a value, not as blank', () => {
    const counts = [{ n: 3 }, { n: 0 }, { n: 1 }]
    expect([...counts].sort(by((c) => c.n)).map((c) => c.n)).toEqual([0, 1, 3])
  })
})

describe('narrowing and ordering together', () => {
  const boards = [
    { name: 'Palau Census 2025', about: 'Field work', widgets: 9, at: '2026-02-01T00:00:00Z' },
    { name: 'Fiji Census 2017', about: '', widgets: 3, at: '2026-02-03T00:00:00Z' },
    { name: 'Vanuatu LFS', about: 'Census frame', widgets: 5, at: '2026-02-02T00:00:00Z' },
  ]

  it('searches across the fields it is given, then orders', () => {
    const shown = arrange(boards, {
      query: 'census',
      searchable: (b) => [b.name, b.about],
      read: (b) => b.widgets,
      direction: 'desc',
    })
    // Vanuatu matches on its description, not its name.
    expect(shown.map((b) => b.name)).toEqual([
      'Palau Census 2025',
      'Vanuatu LFS',
      'Fiji Census 2017',
    ])
  })

  it('leaves the server order alone when nothing is asked of it', () => {
    expect(arrange(boards).map((b) => b.name)).toEqual([
      'Palau Census 2025',
      'Fiji Census 2017',
      'Vanuatu LFS',
    ])
  })

  it('never sorts the array it was handed', () => {
    // It belongs to the query cache; reordering it there reorders it for every
    // other reader of the same data.
    const original = [...boards]
    arrange(boards, { read: (b) => b.name, direction: 'desc' })
    expect(boards).toEqual(original)
  })

  it('keeps the server order for rows the sort cannot separate', () => {
    const tied = [
      { name: 'first', n: 1 },
      { name: 'second', n: 1 },
      { name: 'third', n: 1 },
    ]
    expect(arrange(tied, { read: (t) => t.n }).map((t) => t.name)).toEqual([
      'first',
      'second',
      'third',
    ])
  })

  it('shows nothing when the search matches nothing', () => {
    expect(arrange(boards, { query: 'tonga', searchable: (b) => [b.name] })).toEqual([])
  })
})
