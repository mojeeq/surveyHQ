/**
 * Reading a pasted quota list.
 *
 * Two thousand enumeration areas arrive on a clipboard, not through two
 * thousand number boxes, and the ways that paste goes wrong are quiet ones: a
 * header row counted as a category, a thousands separator read as a column
 * break, Excel's dropped leading zero matching nothing at all.
 */
import { describe, expect, it } from 'vitest'
import { asNumber, matchAgainst, parsePasted } from '@/lib/targets'

describe('parsePasted, a pair per line', () => {
  it('reads comma separated rows', () => {
    const { rows } = parsePasted('EA0508,346\nEA0102,437')

    expect(rows).toEqual([
      { category: 'EA0508', target: 346 },
      { category: 'EA0102', target: 437 },
    ])
  })

  it('reads what a spreadsheet actually puts on the clipboard', () => {
    // Excel and Google Sheets copy as tab separated.
    const { rows } = parsePasted('EA0508\t346\nEA0102\t437')

    expect(rows.map((row) => row.target)).toEqual([346, 437])
  })

  it('drops a header row rather than counting it as a category', () => {
    const parsed = parsePasted('EA_Id,target\nEA0508,346')

    expect(parsed.header).toBe('EA_Id,target')
    expect(parsed.rows).toEqual([{ category: 'EA0508', target: 346 }])
  })

  it('keeps a category that has a comma in it', () => {
    const { rows } = parsePasted('"Shefa, North",120')

    expect(rows).toEqual([{ category: 'Shefa, North', target: 120 }])
  })

  it('reads a thousands separator as part of the number', () => {
    const { rows } = parsePasted('EA0508,15,040')

    expect(rows).toEqual([{ category: 'EA0508', target: 15040 }])
  })

  it('passes over a line with no number in it, and says which', () => {
    const parsed = parsePasted('EA0508,346\nEA0102,\nEA0103,later')

    expect(parsed.rows).toHaveLength(1)
    expect(parsed.skipped).toEqual(['EA0102,', 'EA0103,later'])
  })

  it('keeps the last of a repeated category rather than both', () => {
    const { rows } = parsePasted('EA0508,346\nEA0508,400')

    expect(rows).toEqual([{ category: 'EA0508', target: 400 }])
  })

  it('reads a space between the two, which is what a PDF copy gives', () => {
    const { rows } = parsePasted('EA0508 346')

    expect(rows).toEqual([{ category: 'EA0508', target: 346 }])
  })
})

describe('parsePasted, one column of numbers', () => {
  const order = ['EA0101', 'EA0102', 'EA0103']

  it('lands the numbers on the categories in the order given', () => {
    const { rows } = parsePasted('10\n20\n30', order)

    expect(rows).toEqual([
      { category: 'EA0101', target: 10 },
      { category: 'EA0102', target: 20 },
      { category: 'EA0103', target: 30 },
    ])
  })

  it('stops where the categories run out rather than inventing them', () => {
    const parsed = parsePasted('10\n20\n30\n40', order)

    expect(parsed.rows).toHaveLength(3)
    expect(parsed.skipped).toEqual(['40'])
  })

  it('has nothing to attach to without the list on screen', () => {
    // Guessing which category a bare column belongs to is how a quota ends up
    // on the wrong area, so it comes back empty instead.
    expect(parsePasted('10\n20').rows).toEqual([])
  })

  it('reads a short column as far as it goes', () => {
    const { rows } = parsePasted('10\n20', order)

    expect(rows.map((row) => row.category)).toEqual(['EA0101', 'EA0102'])
  })
})

describe('asNumber', () => {
  it('takes the ways a spreadsheet writes one', () => {
    expect(asNumber('1234')).toBe(1234)
    expect(asNumber('1,234')).toBe(1234)
    expect(asNumber('1 234')).toBe(1234)
    expect(asNumber('1234.5')).toBe(1234.5)
    expect(asNumber('0')).toBe(0)
  })

  it('refuses what is not one', () => {
    expect(asNumber('')).toBeNull()
    expect(asNumber('   ')).toBeNull()
    expect(asNumber('later')).toBeNull()
    expect(asNumber('12a')).toBeNull()
  })
})

describe('matchAgainst', () => {
  it('reports what matched, what the data does not have, and what was left out', () => {
    const found = matchAgainst(['EA01', 'EA02', 'EA99'], ['EA01', 'EA02', 'EA03'])

    expect(found.matched).toEqual(['EA01', 'EA02'])
    expect(found.unknown).toEqual(['EA99'])
    expect(found.missing).toEqual(['EA03'])
  })

  it('catches the leading zero Excel drops', () => {
    // The whole point: 508 against data keyed 0508 matches nothing, silently,
    // at two thousand rows.
    const found = matchAgainst(['508'], ['0508'])

    expect(found.matched).toEqual([])
    expect(found.unknown).toEqual(['508'])
  })
})
