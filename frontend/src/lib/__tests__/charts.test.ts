/**
 * What a chart is built to say.
 *
 * This file is the arithmetic between a query result and the marks on a
 * dashboard: the ordering, the fold into "Other", the percentages of a
 * composition, the five numbers of a box. None of it had a test, and it is the
 * one place in the frontend where a bug is a *wrong number* on a report rather
 * than something that looks wrong - a bar of the right height for the figure it
 * was given, and the figure quietly not what the data says.
 *
 * So these pin the figures, not the styling. Colours, fonts and label widths
 * are judgement that a test can only restate; a total that does not add up is a
 * fact that can be checked.
 */

import { describe, expect, it } from 'vitest'

import {
  BOX_MEASURES,
  MAX_SERIES,
  buildChartOption,
  buildSparkline,
  themeColors,
  twoLines,
} from '@/lib/charts'
import type { ChartType, QueryColumn, QueryResult } from '@/lib/types'

function column(name: string, type: 'dimension' | 'measure'): QueryColumn {
  return { name, label: name, type, data_type: type === 'measure' ? 'number' : 'text' }
}

function result(columns: QueryColumn[], rows: unknown[][]): QueryResult {
  return {
    columns,
    rows,
    row_count: rows.length,
    truncated: false,
    sql: '',
    duration_ms: 0,
  }
}

/** One dimension, one measure: the shape most widgets are. */
function simple(pairs: [string, number | null][]): QueryResult {
  return result(
    [column('province', 'dimension'), column('interviews', 'measure')],
    pairs.map(([name, value]) => [name, value]),
  )
}

/** Two dimensions and a measure, which is what a cross-tab comes back as. */
function crosstab(rows: [string, string, number][]): QueryResult {
  return result(
    [
      column('province', 'dimension'),
      column('education', 'dimension'),
      column('people', 'measure'),
    ],
    rows.map(([a, b, n]) => [a, b, n]),
  )
}

/** The series ECharts was handed, as plain numbers. */
function seriesOf(option: ReturnType<typeof buildChartOption>) {
  const series = (option as { series?: unknown }).series
  return (Array.isArray(series) ? series : [series]).filter(Boolean) as {
    name?: string
    data?: unknown[]
  }[]
}

function categoriesOf(option: ReturnType<typeof buildChartOption>) {
  const option_ = option as { xAxis?: unknown; yAxis?: unknown }
  for (const axis of [option_.xAxis, option_.yAxis]) {
    const found = Array.isArray(axis) ? axis[0] : axis
    const data = (found as { data?: unknown })?.data
    if (Array.isArray(data)) return data as string[]
  }
  return []
}

// --- the numbers a bar is drawn from -----------------------------------------

describe('a simple bar chart', () => {
  it('draws one bar per row, in the order the query returned them', () => {
    const option = buildChartOption(
      simple([
        ['Northern', 120],
        ['Highland', 80],
        ['Southern', 200],
      ]),
      'bar',
      {},
    )
    expect(categoriesOf(option)).toEqual(['Northern', 'Highland', 'Southern'])
    expect(seriesOf(option)[0].data).toEqual([120, 80, 200])
  })

  it('keeps a missing value missing rather than drawing it as nothing', () => {
    // A province that reported no interviews and a province that reported zero
    // are different facts, and a chart that draws both as a bar of height zero
    // has lost one of them.
    const option = buildChartOption(
      simple([
        ['Northern', 120],
        ['Highland', null],
        ['Southern', 0],
      ]),
      'bar',
      {},
    )
    expect(seriesOf(option)[0].data).toEqual([120, null, 0])
  })
})

// --- ordering ----------------------------------------------------------------

describe('ordering the categories', () => {
  const data = simple([
    ['Northern', 120],
    ['Highland', 80],
    ['Southern', 200],
  ])

  it('largest first', () => {
    const option = buildChartOption(data, 'bar', { sort: 'value_desc' })
    expect(categoriesOf(option)).toEqual(['Southern', 'Northern', 'Highland'])
    expect(seriesOf(option)[0].data).toEqual([200, 120, 80])
  })

  it('smallest first', () => {
    const option = buildChartOption(data, 'bar', { sort: 'value_asc' })
    expect(seriesOf(option)[0].data).toEqual([80, 120, 200])
  })

  it('by label, reading numbers as numbers', () => {
    // Age bands come back as "0", "5", "10", ... and sorting those as text puts
    // 5 between 45 and 50, which on a pyramid is a chart nobody can read.
    const bands = simple([
      ['45', 3],
      ['5', 1],
      ['10', 2],
      ['0', 9],
    ])
    expect(categoriesOf(buildChartOption(bands, 'bar', { sort: 'label_asc' }))).toEqual([
      '0',
      '5',
      '10',
      '45',
    ])
  })

  it('by label, as words when they are words', () => {
    const option = buildChartOption(data, 'bar', { sort: 'label_asc' })
    expect(categoriesOf(option)).toEqual(['Highland', 'Northern', 'Southern'])
  })

  it('moves the values with their labels, never just the labels', () => {
    // The failure worth guarding: an order applied to the axis and not to the
    // data draws every bar against the wrong name, and every bar is still a
    // plausible height.
    const option = buildChartOption(data, 'bar', { sort: 'value_desc' })
    const names = categoriesOf(option)
    const values = seriesOf(option)[0].data as number[]
    expect(Object.fromEntries(names.map((name, i) => [name, values[i]]))).toEqual({
      Northern: 120,
      Highland: 80,
      Southern: 200,
    })
  })
})

// --- folding the tail --------------------------------------------------------

describe('folding the tail into Other', () => {
  const forty = simple(
    Array.from({ length: 12 }, (_, i) => [`P${i}`, (12 - i) * 10] as [string, number]),
  )

  it('keeps the largest N and adds them all up into one Other', () => {
    const option = buildChartOption(forty, 'bar', { topN: 3, sort: 'value_desc' })
    const names = categoriesOf(option)
    const values = seriesOf(option)[0].data as number[]
    expect(names.slice(0, 3)).toEqual(['P0', 'P1', 'P2'])
    expect(names[3]).toBe('Other (9)')
    // 120+110+100 kept; the remaining nine are 90 down to 10.
    expect(values.slice(0, 3)).toEqual([120, 110, 100])
    expect(values[3]).toBe(90 + 80 + 70 + 60 + 50 + 40 + 30 + 20 + 10)
  })

  it('loses nothing: the folded total is the whole total', () => {
    const whole = 12 * 13 * 10 / 2 - 0 // 10+20+...+120
    const option = buildChartOption(forty, 'bar', { topN: 4 })
    const values = seriesOf(option)[0].data as number[]
    expect(values.reduce((sum, n) => sum + n, 0)).toBe(whole)
  })

  it('folds the small ones even when the axis is in another order', () => {
    // "Other" means the small ones, not the last ones alphabetically.
    const option = buildChartOption(forty, 'bar', { topN: 3, sort: 'label_asc' })
    const names = categoriesOf(option)
    expect(names[names.length - 1]).toBe('Other (9)')
    expect(names.slice(0, 3).sort()).toEqual(['P0', 'P1', 'P2'])
  })

  it('leaves a short list alone', () => {
    const option = buildChartOption(forty, 'bar', { topN: 50 })
    expect(categoriesOf(option)).toHaveLength(12)
    expect(categoriesOf(option).join(' ')).not.toContain('Other')
  })
})

// --- composition -------------------------------------------------------------

describe('stacking to 100%', () => {
  const split = crosstab([
    ['Northern', 'Primary', 30],
    ['Northern', 'Secondary', 10],
    ['Highland', 'Primary', 25],
    ['Highland', 'Secondary', 75],
  ])

  it('every category adds to 100', () => {
    const option = buildChartOption(split, 'bar', { percentStack: true, stacked: true })
    const series = seriesOf(option)
    const names = categoriesOf(option)
    for (let i = 0; i < names.length; i += 1) {
      const total = series.reduce((sum, s) => sum + Number((s.data as number[])[i] ?? 0), 0)
      expect(total).toBeCloseTo(100, 6)
    }
  })

  it('keeps the proportions the counts had', () => {
    const option = buildChartOption(split, 'bar', { percentStack: true, stacked: true })
    const series = seriesOf(option)
    const primary = series.find((s) => s.name === 'Primary')!.data as number[]
    const names = categoriesOf(option)
    expect(primary[names.indexOf('Northern')]).toBeCloseTo(75, 6)
    expect(primary[names.indexOf('Highland')]).toBeCloseTo(25, 6)
  })

  it('a category with nothing in it is blank, not nought per cent', () => {
    const empty = crosstab([
      ['Northern', 'Primary', 30],
      ['Western', 'Primary', 0],
    ])
    const option = buildChartOption(empty, 'bar', { percentStack: true, stacked: true })
    const data = seriesOf(option)[0].data as (number | null)[]
    expect(data[categoriesOf(option).indexOf('Western')]).toBeNull()
  })
})

// --- cross-tabs --------------------------------------------------------------

describe('a cross-tab', () => {
  it('becomes one series per value of the second dimension', () => {
    const option = buildChartOption(
      crosstab([
        ['Northern', 'Primary', 30],
        ['Northern', 'Secondary', 10],
        ['Highland', 'Primary', 25],
        ['Highland', 'Secondary', 75],
      ]),
      'bar',
      {},
    )
    const series = seriesOf(option)
    expect(series.map((s) => s.name)).toEqual(['Primary', 'Secondary'])
    const names = categoriesOf(option)
    expect(names).toEqual(['Northern', 'Highland'])
    expect(series[0].data).toEqual([30, 25])
    expect(series[1].data).toEqual([10, 75])
  })

  it('leaves a combination that never occurred empty', () => {
    const option = buildChartOption(
      crosstab([
        ['Northern', 'Primary', 30],
        ['Highland', 'Secondary', 75],
      ]),
      'bar',
      {},
    )
    const series = seriesOf(option)
    // Nobody in Highland reported Primary. That is a gap, not a zero.
    expect((series[0].data as unknown[])[1]).toBeNull()
  })
})

describe('a cross-tab with more series than there are colours', () => {
  const twelve = crosstab(
    ['Northern', 'Highland'].flatMap((province) =>
      Array.from(
        { length: 12 },
        (_, i) => [province, `Level ${i + 1}`, 10] as [string, string, number],
      ),
    ),
  )

  it('does not silently drop the ones past the eighth', () => {
    // MAX_SERIES is documented as the point where "the tail is folded into
    // Other". For categories it is. For the series of a cross-tab the tail was
    // simply sliced off - so a stacked bar of twelve education levels drew
    // eight of them, every bar came up short, and nothing on the chart said a
    // third of the people were missing.
    const option = buildChartOption(twelve, 'bar', { stacked: true })
    const series = seriesOf(option)
    const names = categoriesOf(option)
    const drawn = names.map((_, i) =>
      series.reduce((sum, s) => sum + Number((s.data as number[])[i] ?? 0), 0),
    )
    expect(drawn).toEqual([120, 120])
  })

  it('still draws no more series than the palette has colours', () => {
    const series = seriesOf(buildChartOption(twelve, 'bar', { stacked: true }))
    expect(series.length).toBeLessThanOrEqual(MAX_SERIES)
  })
})

// --- the parts that are not a bar -------------------------------------------

describe('other marks', () => {
  it('a pie carries a name and a value for each slice', () => {
    const option = buildChartOption(
      simple([
        ['Northern', 120],
        ['Highland', 80],
      ]),
      'pie',
      {},
    )
    expect(seriesOf(option)[0].data).toEqual([
      expect.objectContaining({ name: 'Northern', value: 120 }),
      expect.objectContaining({ name: 'Highland', value: 80 }),
    ])
  })

  it('a sparkline is the measure, in order, and nothing else', () => {
    const line = buildSparkline([
      { t: '2026-01-01', v: 3 },
      { t: '2026-01-02', v: 1 },
      { t: '2026-01-03', v: null },
      { t: '2026-01-04', v: 5 },
    ])
    const series = (line as { series?: { data?: unknown[] }[] }).series ?? []
    expect(series[0].data).toEqual([3, 1, null, 5])
  })

  it('an unknown theme falls back rather than drawing colourless', () => {
    expect(themeColors('no such theme')).toEqual(themeColors('default'))
    expect(themeColors(null)).toEqual(themeColors('default'))
    expect(themeColors(undefined).length).toBeGreaterThan(0)
  })

  it('every theme offers a colour for every series a chart will draw', () => {
    // A palette shorter than MAX_SERIES leaves the last series undefined, which
    // ECharts draws in whatever it defaults to - and two series then share a
    // colour with nothing saying so.
    for (const name of ['default', 'vivid', 'bold']) {
      expect(themeColors(name).length).toBeGreaterThanOrEqual(MAX_SERIES)
    }
  })
})

// --- nothing to draw ---------------------------------------------------------

describe('an empty result', () => {
  it('builds an option rather than throwing', () => {
    const empty = result(
      [column('province', 'dimension'), column('interviews', 'measure')],
      [],
    )
    expect(() => buildChartOption(empty, 'bar', {})).not.toThrow()
    expect(categoriesOf(buildChartOption(empty, 'bar', {}))).toEqual([])
  })

  it('survives a result with no measure at all', () => {
    const noMeasure = result([column('province', 'dimension')], [['Northern'], ['Highland']])
    expect(() => buildChartOption(noMeasure, 'bar', {})).not.toThrow()
  })
})

// --- where the tooltip is hung ----------------------------------------------

describe('a tooltip that is wider than the widget it belongs to', () => {
  /**
   * Every chart that has a tooltip hangs it off <body>.
   *
   * A dashboard widget is a card with its contents clipped, which is right for
   * the contents. A tooltip is not contents - it floats over the page - and
   * one cut off at the card's edge is the one case where the label is the
   * whole point: a donut of interview statuses in a quarter-width panel showed
   * "rovedByHeadquarters" and half a percentage.
   *
   * It only bites when the tooltip is wider than the chart, because ECharts
   * keeps one inside while it fits. That is why it has to be every chart
   * rather than the ones somebody noticed: whether a label is too long is a
   * property of the data, not of the chart type.
   */
  // Every kind that draws a tooltip from one dimension and one measure. The
  // two left out need their own shape to draw at all, and have their own
  // assertions below - leaving them to a `if (tooltip)` guard here would let
  // this whole block pass on a build that had stopped drawing tooltips.
  const everyKind: ChartType[] = [
    'bar', 'horizontal_bar', 'stacked_bar', 'horizontal_stacked_bar',
    'line', 'area', 'pie', 'donut', 'scatter', 'heatmap', 'gauge', 'funnel',
  ]

  it.each(everyKind)('hangs %s off the body, not the chart', (kind) => {
    const option = buildChartOption(
      simple([['Western', 120], ['Highland', 90], ['Northern', 60]]),
      kind,
    ) as { tooltip?: { appendToBody?: boolean } }
    expect(option.tooltip?.appendToBody).toBe(true)
  })

  it('hangs the sparkline off the body too', () => {
    const option = buildSparkline([
      { t: '2026-02-01', v: 1 },
      { t: '2026-02-02', v: 4 },
      { t: '2026-02-03', v: 2 },
    ]) as { tooltip?: { appendToBody?: boolean } }
    expect(option.tooltip?.appendToBody).toBe(true)
  })

  it('hangs a population pyramid off the body', () => {
    const option = buildChartOption(
      result(
        [
          column('age_band', 'dimension'),
          column('sex', 'dimension'),
          column('people', 'measure'),
        ],
        [
          ['0-4', 'Male', 410],
          ['0-4', 'Female', 395],
          ['5-9', 'Male', 380],
          ['5-9', 'Female', 372],
        ],
      ),
      'population_pyramid',
    ) as { tooltip?: { appendToBody?: boolean } }
    expect(option.tooltip?.appendToBody).toBe(true)
  })

  it('hangs a box plot off the body', () => {
    const option = buildChartOption(
      result(
        [
          column('province', 'dimension'),
          ...BOX_MEASURES.map((measure) => column(measure.alias, 'measure')),
        ],
        [['Western', 12, 22, 31, 44, 68]],
      ),
      'boxplot',
    ) as { tooltip?: { appendToBody?: boolean } }
    expect(option.tooltip?.appendToBody).toBe(true)
  })
})

// --- an axis with an order of its own ----------------------------------------

/** One date grouping and a measure, as a chart of fieldwork over time is. */
function overTime(pairs: [string, number][]): QueryResult {
  return result(
    [
      { name: 'day', label: 'Day', type: 'dimension', data_type: 'datetime' },
      column('interviews', 'measure'),
    ],
    pairs.map(([day, value]) => [day, value]),
  )
}

/** A date grouping and a second dimension: a line per status over time. */
function overTimeBy(rows: [string, string, number][]): QueryResult {
  return result(
    [
      { name: 'day', label: 'Day', type: 'dimension', data_type: 'datetime' },
      column('status', 'dimension'),
      column('interviews', 'measure'),
    ],
    rows.map(([day, status, value]) => [day, status, value]),
  )
}

describe('a chart over time', () => {
  // The rows as a query sorted by size hands them over: biggest day first.
  const scattered = overTime([
    ['2026-08-03', 440],
    ['2026-07-15', 360],
    ['2026-07-08', 290],
    ['2026-07-23', 320],
    ['2026-07-09', 230],
  ])

  it('is drawn in time order whatever the sort asks for', () => {
    for (const sort of ['value_desc', 'value_asc', 'label_desc', 'none'] as const) {
      expect(categoriesOf(buildChartOption(scattered, 'line', { sort }))).toEqual([
        '2026-07-08',
        '2026-07-09',
        '2026-07-15',
        '2026-07-23',
        '2026-08-03',
      ])
    }
  })

  it('carries each day its own value, not the one next to it', () => {
    const option = buildChartOption(scattered, 'line', { sort: 'value_desc' })
    const names = categoriesOf(option)
    const values = seriesOf(option)[0].data as number[]
    expect(Object.fromEntries(names.map((name, i) => [name, values[i]]))).toEqual({
      '2026-07-08': 290,
      '2026-07-09': 230,
      '2026-07-15': 360,
      '2026-07-23': 320,
      '2026-08-03': 440,
    })
  })

  it('reads months and years in time order, not as text', () => {
    const months = overTime([
      ['2026-10', 5],
      ['2026-09', 9],
      ['2027-01', 1],
    ])
    expect(categoriesOf(buildChartOption(months, 'line', { sort: 'value_desc' }))).toEqual([
      '2026-09',
      '2026-10',
      '2027-01',
    ])
  })

  it('puts one line per series over the same ordered axis', () => {
    const option = buildChartOption(
      overTimeBy([
        ['2026-08-03', 'Completed', 440],
        ['2026-07-08', 'Completed', 290],
        ['2026-07-08', 'Approved', 12],
        ['2026-08-03', 'Approved', 30],
      ]),
      'line',
      { sort: 'value_desc' },
    )
    expect(categoriesOf(option)).toEqual(['2026-07-08', '2026-08-03'])
    const byName = Object.fromEntries(seriesOf(option).map((s) => [s.name, s.data]))
    expect(byName.Completed).toEqual([290, 440])
    expect(byName.Approved).toEqual([12, 30])
  })

  it('still folds the smallest days into Other, at the end', () => {
    const option = buildChartOption(scattered, 'line', { sort: 'value_desc', topN: 3 })
    const names = categoriesOf(option)
    // The three busiest days are kept, in date order, and the rest add up.
    expect(names).toEqual(['2026-07-15', '2026-07-23', '2026-08-03', 'Other (2)'])
    expect((seriesOf(option)[0].data as number[])[3]).toBe(290 + 230)
  })
})

describe('a chart of a number', () => {
  const bands = result(
    [
      { name: 'age', label: 'Age', type: 'dimension', data_type: 'numeric' },
      column('people', 'measure'),
    ],
    [
      ['30', 60],
      ['0', 116],
      ['80', 12],
      ['10', 141],
      ['20', 95],
    ],
  )

  it('reads low to high however the rows arrive', () => {
    expect(categoriesOf(buildChartOption(bands, 'bar', { sort: 'value_desc' }))).toEqual([
      '0',
      '10',
      '20',
      '30',
      '80',
    ])
  })

  it('does not read a band as a year', () => {
    const years = result(
      [
        { name: 'built', label: 'Year built', type: 'dimension', data_type: 'numeric' },
        column('houses', 'measure'),
      ],
      [
        ['2026', 3],
        ['198', 9],
        ['45', 1],
      ],
    )
    expect(categoriesOf(buildChartOption(years, 'bar', { sort: 'value_desc' }))).toEqual([
      '45',
      '198',
      '2026',
    ])
  })
})

describe('a chart of categories', () => {
  it('still reads biggest first', () => {
    const option = buildChartOption(
      simple([
        ['Northern', 120],
        ['Southern', 200],
        ['Highland', 80],
      ]),
      'bar',
      { sort: 'value_desc' },
    )
    expect(categoriesOf(option)).toEqual(['Southern', 'Northern', 'Highland'])
  })

  it('still reads by name when asked', () => {
    const option = buildChartOption(
      simple([
        ['Northern', 120],
        ['Southern', 200],
        ['Highland', 80],
      ]),
      'bar',
      { sort: 'label_asc' },
    )
    expect(categoriesOf(option)).toEqual(['Highland', 'Northern', 'Southern'])
  })
})

// --- the other ways to draw a tick-all-that-apply question -------------------

/** A share column, as the multiple-select views return one. */
function shares(rows: [string, string, number | null][]): QueryResult {
  return result(
    [
      column('option', 'dimension'),
      column('group', 'dimension'),
      { name: 'percent', label: '% of respondents', type: 'measure', data_type: 'percent' },
    ],
    rows,
  )
}

describe('shares by group', () => {
  const ten = shares(
    ['Piped', 'Well'].flatMap((option) =>
      Array.from({ length: 10 }, (_, i) => [option, `District ${i + 1}`, 40] as [string, string, number]),
    ),
  )

  it('are never added up into an Other', () => {
    // Forty per cent of one district plus forty of another is not eighty per
    // cent of anything, so the ninth and tenth districts keep bars of their own.
    const names = seriesOf(buildChartOption(ten, 'horizontal_bar')).map((s) => s.name)
    expect(names).toHaveLength(10)
    expect(names.some((name) => name?.startsWith('Other'))).toBe(false)
  })

  it('every group keeps a row on a heatmap', () => {
    const option = buildChartOption(ten, 'heatmap', { transpose: true }) as any
    expect(option.xAxis.data).toHaveLength(10)
    expect(option.yAxis.data).toEqual(['Piped', 'Well'])
  })
})

describe('a heatmap', () => {
  const together = shares([
    ['Piped', 'Piped', null],
    ['Piped', 'Rain', 66.7],
    ['Rain', 'Piped', 50],
    ['Rain', 'Rain', null],
  ])

  it('draws no cell where the result left one empty', () => {
    const cells = (seriesOf(buildChartOption(together, 'heatmap'))[0].data as any[]).map(
      (cell) => cell.value,
    )
    expect(cells).toEqual([
      [1, 0, 50],
      [0, 1, 66.7],
    ])
  })

  it('names each cell by its own category, which is what a click filters by', () => {
    // The first cell drawn is Rain's, not the first row of the result.
    for (const transpose of [false, true]) {
      const cells = (seriesOf(buildChartOption(together, 'heatmap', { transpose }))[0]
        .data as any[]).map((cell) => cell.name)
      expect(cells).toEqual(['Rain', 'Piped'])
    }
  })

  it('puts the first dimension down the side when transposed', () => {
    const option = buildChartOption(together, 'heatmap', { transpose: true }) as any
    expect(option.yAxis.data).toEqual(['Piped', 'Rain'])
    // Piped's row, Rain's column: x is the second dimension now.
    const cells = (option.series[0].data as any[]).map((cell) => cell.value)
    expect(cells).toContainEqual([1, 0, 66.7])
  })

  it('still draws a combination that never occurred as a nought', () => {
    // Absent from the result is "none", which is a count; only a cell the
    // result itself left empty is left off the map.
    const option = buildChartOption(
      crosstab([
        ['Northern', 'Primary', 4],
        ['Southern', 'Secondary', 2],
      ]),
      'heatmap',
    )
    expect((seriesOf(option)[0].data as any[]).length).toBe(4)
  })
})

describe('bar styles', () => {
  const options = simple([
    ['Piped', 50],
    ['Rain', 66.7],
    ['River', null],
  ])

  it('a lollipop is a thin stem and a dot at the same value', () => {
    const [stem, dot] = seriesOf(buildChartOption(options, 'horizontal_bar', { barStyle: 'lollipop' })) as any[]
    expect(stem.type).toBe('bar')
    expect(stem.barWidth).toBe(2)
    expect(dot.type).toBe('scatter')
    expect(dot.data).toEqual([
      { name: 'Piped', value: [50, 0] },
      { name: 'Rain', value: [66.7, 1] },
      null,
    ])
  })

  it('a track runs to a hundred where the figures are shares', () => {
    const percents = result(
      [
        column('option', 'dimension'),
        { name: 'percent', label: '% of respondents', type: 'measure', data_type: 'percent' },
      ],
      [
        ['Piped', 50],
        ['Rain', 66.7],
      ],
    )
    const option = buildChartOption(percents, 'horizontal_bar', { barStyle: 'track' }) as any
    expect(option.series[0].showBackground).toBe(true)
    expect(option.xAxis.max).toBe(100)
  })

  it('a track over counts runs to the end of the axis, however small they are', () => {
    // Counts of 3 and 6 are not out of a hundred because neither passed it.
    const counts = simple([
      ['Piped', 3],
      ['Rain', 6],
    ])
    const option = buildChartOption(counts, 'horizontal_bar', { barStyle: 'track' }) as any
    expect(option.series[0].showBackground).toBe(true)
    expect(option.xAxis.max).toBeUndefined()
  })

  it('several series are plain bars whatever the style', () => {
    const option = buildChartOption(
      crosstab([
        ['Northern', 'Primary', 4],
        ['Northern', 'Secondary', 2],
      ]),
      'bar',
      { barStyle: 'lollipop' },
    )
    expect(seriesOf(option).every((s: any) => s.type === 'bar')).toBe(true)
  })
})

describe('a long name wrapped', () => {
  it('stays on one line when it fits', () => {
    expect(twoLines('None', 20)).toBe('None')
  })

  it('breaks between words onto a second line', () => {
    expect(twoLines('Soap and single lever type tap', 18)).toBe('Soap and single\nlever type tap')
  })

  it('is cut after two lines, so it cannot run into the next', () => {
    const shown = twoLines('Soap and single lever type tap + Liquid soap contained in a dispenser', 20)
    expect(shown.split('\n')).toHaveLength(2)
    expect(shown.endsWith('…')).toBe(true)
  })
})
