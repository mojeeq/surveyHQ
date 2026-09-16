/**
 * A survey answer must not become script in a chart tooltip.
 *
 * ECharts assigns a tooltip `formatter`'s return value as innerHTML, and there
 * is no way to ask it for text instead. React escapes everything it renders,
 * so everywhere else in this application a label is already just characters -
 * a tooltip formatter is the exception, and every one of them interpolates a
 * label that came out of an uploaded file.
 *
 * Checked against every chart type rather than the ones that happened to be
 * reported: a formatter added for a new chart type is exactly how this comes
 * back.
 */

import { describe, expect, it } from 'vitest'

import { BOX_MEASURES, buildChartOption } from '../charts'
import { escapeHtml } from '../format'
import type { ChartType, QueryResult } from '../types'

/** A value label as it arrives from a .dta, an export, or a free-text answer. */
const PAYLOAD = '<img src=x onerror="alert(1)">'

const KINDS: ChartType[] = [
  'bar',
  'horizontal_bar',
  'stacked_bar',
  'horizontal_stacked_bar',
  'population_pyramid',
  'line',
  'area',
  'donut',
  'pie',
  'scatter',
  'boxplot',
  'heatmap',
]

/** Chart types that read a second dimension rather than one. */
const TWO_DIMENSION = new Set<ChartType>([
  'stacked_bar',
  'horizontal_stacked_bar',
  'population_pyramid',
  'heatmap',
])

function resultFor(kind: ChartType): QueryResult {
  // A box plot reads five named measures per group and draws an explanatory
  // placeholder without them, so giving it the wrong shape would quietly test
  // nothing. That is how its formatter escaped the first sweep of this.
  if (kind === 'boxplot') {
    return {
      columns: [
        { name: 'region', label: 'Region', type: 'dimension', data_type: 'text' },
        ...BOX_MEASURES.map((m) => ({
          name: m.alias,
          label: m.label,
          type: 'measure' as const,
          data_type: 'number' as const,
        })),
      ],
      rows: [
        [PAYLOAD, 1, 2, 3, 4, 5],
        ['Shefa', 2, 3, 4, 5, 6],
      ],
      row_count: 2,
      truncated: false,
      sql: '',
      duration_ms: 0,
    } as QueryResult
  }
  const twoDim = TWO_DIMENSION.has(kind)
  return {
    columns: twoDim
      ? [
          { name: 'region', label: 'Region', type: 'dimension', data_type: 'text' },
          { name: 'sex', label: 'Sex', type: 'dimension', data_type: 'text' },
          { name: 'n', label: 'Interviews', type: 'measure', data_type: 'number' },
        ]
      : [
          { name: 'region', label: 'Region', type: 'dimension', data_type: 'text' },
          { name: 'n', label: 'Interviews', type: 'measure', data_type: 'number' },
        ],
    // The payload is on both dimensions: a tooltip names the category and the
    // series, and both are values out of the data.
    rows: twoDim
      ? [
          [PAYLOAD, PAYLOAD, 40],
          ['Shefa', 'F', 30],
        ]
      : [
          [PAYLOAD, 40],
          ['Shefa', 60],
        ],
    row_count: 2,
    truncated: false,
    sql: '',
    duration_ms: 0,
  } as QueryResult
}

/** Every tooltip formatter in an option, wherever it is nested. */
function formatters(option: unknown): ((params: unknown) => string)[] {
  const found: ((params: unknown) => string)[] = []
  const walk = (node: unknown, insideTooltip: boolean) => {
    if (Array.isArray(node)) {
      node.forEach((child) => walk(child, insideTooltip))
      return
    }
    if (!node || typeof node !== 'object') return
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      if (key === 'formatter' && insideTooltip && typeof value === 'function') {
        found.push(value as (params: unknown) => string)
      } else {
        walk(value, insideTooltip || key === 'tooltip')
      }
    }
  }
  walk(option, false)
  return found
}

/**
 * The shapes ECharts hands a formatter, across triggers.
 *
 * A formatter reaches into whichever of these its chart type uses, so every
 * one is offered the payload and the rest is filled in plausibly. Anything
 * that throws on a shape it does not recognise is skipped rather than failed:
 * the question here is what it returns when it does run.
 */
function paramShapes() {
  const base = {
    marker: '<span style="background:#000"></span>',
    name: PAYLOAD,
    seriesName: PAYLOAD,
    axisValueLabel: PAYLOAD,
    axisValue: PAYLOAD,
    dataIndex: 0,
    percent: 50,
    value: 40,
  }
  return [
    base,
    { ...base, value: [0, 0, 40] },
    { ...base, value: [40, 12] },
    { ...base, value: [0, 1, 2, 3, 4, 5] },
    [base],
    [{ ...base, value: [0, 0, 40] }],
  ]
}

let exercised = 0

describe('chart tooltips', () => {
  it.each(KINDS)('%s does not put a survey answer into the page as markup', (kind) => {
    const option = buildChartOption(resultFor(kind), kind, {})
    const found = formatters(option)
    // Not every chart type writes its own formatter. Those that do not fall
    // back to the one ECharts ships, which escapes - so an absence here is a
    // safe answer rather than an untested one. The suite-wide floor below is
    // what stops this going quiet altogether.
    exercised += found.length

    let ran = 0
    for (const formatter of found) {
      for (const params of paramShapes()) {
        let html: string
        try {
          html = String(formatter(params))
        } catch {
          continue
        }
        ran += 1
        // The payload must never come back as itself.
        expect(html).not.toContain(PAYLOAD)

        // And the stronger form, which does not depend on what the payload
        // happens to be: the only tags in the output are the ones the
        // formatter writes itself. `marker` is ECharts' own colour swatch and
        // is meant to be markup, so a span is expected; anything else in
        // angle brackets came out of the data.
        for (const tag of html.match(/<[^>]*>/g) ?? []) {
          expect(tag, `${kind} let a tag through: ${tag}`).toMatch(
            /^<\/?(?:br|b|span)[\s/>]/,
          )
        }
      }
    }
    if (found.length) expect(ran, `${kind} never ran a formatter`).toBeGreaterThan(0)
  })

  it('is still actually checking something', () => {
    // A guard against the failure this file is most likely to suffer: a
    // refactor moves the formatters somewhere the walker above does not look,
    // every case finds nothing, and the suite passes while testing air.
    expect(exercised).toBeGreaterThanOrEqual(6)
  })
})

describe('escapeHtml', () => {
  it('defangs every character that could open a tag or an attribute', () => {
    expect(escapeHtml(`<img src=x onerror="alert(1)">`)).toBe(
      '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;',
    )
    expect(escapeHtml("it's & so")).toBe('it&#39;s &amp; so')
  })

  it('renders an absent label as nothing rather than the word undefined', () => {
    expect(escapeHtml(null)).toBe('')
    expect(escapeHtml(undefined)).toBe('')
  })
})
