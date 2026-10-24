/**
 * Every chart the builder makes draws with the parts lib/echarts.ts registers.
 *
 * ECharts is registered piece by piece so the first page does not download all
 * of it. The cost is that a chart type or component added to a builder and not
 * registered draws nothing - ECharts says "used but not imported" and leaves an
 * empty box. So every chart the builder can produce is rendered here, server
 * side, through exactly that registration, and any such complaint fails.
 */
import * as echarts from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { BOX_MEASURES, buildChartOption, buildSparkline } from '@/lib/charts'
import { PARTS } from '@/lib/echarts'
import type { ChartType, QueryColumn, QueryResult } from '@/lib/types'

function column(name: string, type: 'dimension' | 'measure'): QueryColumn {
  return { name, label: name, type, data_type: type === 'measure' ? 'number' : 'text' }
}

function result(columns: QueryColumn[], rows: unknown[][]): QueryResult {
  return { columns, rows, row_count: rows.length, truncated: false, sql: '', duration_ms: 0 }
}

const ONE = result(
  [column('province', 'dimension'), column('interviews', 'measure')],
  [['Northern', 12], ['Highland', 30], ['Southern', 7]],
)
const TWO = result(
  [column('province', 'dimension'), column('sex', 'dimension'), column('people', 'measure')],
  [['Northern', 'Male', 5], ['Northern', 'Female', 7], ['Highland', 'Male', 9], ['Highland', 'Female', 4]],
)
const PAIRS = result(
  [column('age', 'measure'), column('income', 'measure')],
  [[20, 100], [35, 250], [50, 180]],
)
const BOXES = result(
  [column('province', 'dimension'), ...BOX_MEASURES.map((m) => column(m.alias, 'measure'))],
  [['Western', 12, 22, 31, 44, 68], ['Eastern', 5, 15, 20, 30, 50]],
)

/** Every chart type the builder draws with ECharts, and the data it needs. */
const CASES: [ChartType, QueryResult][] = [
  ['bar', ONE],
  ['bar', TWO],
  ['horizontal_bar', ONE],
  ['stacked_bar', TWO],
  ['horizontal_stacked_bar', TWO],
  ['population_pyramid', TWO],
  ['line', ONE],
  ['line', TWO],
  ['area', TWO],
  ['pie', ONE],
  ['donut', ONE],
  ['scatter', PAIRS],
  ['heatmap', TWO],
  ['funnel', ONE],
  ['boxplot', BOXES],
  ['gauge', ONE],
]

/** A mark of any kind, beyond the empty frame an unregistered chart leaves. */
const DRAWN = /<(path|polygon|polyline|rect|circle)\b/

const complaints: unknown[][] = []

beforeAll(() => {
  // What the app registers, and a renderer that works without a canvas.
  echarts.use([...PARTS, SVGRenderer])
})

afterEach(() => {
  vi.restoreAllMocks()
  complaints.length = 0
})

function draw(option: ReturnType<typeof buildChartOption>): string {
  const listen = (...args: unknown[]) => complaints.push(args)
  vi.spyOn(console, 'warn').mockImplementation(listen)
  vi.spyOn(console, 'error').mockImplementation(listen)
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 480, height: 320 })
  chart.setOption(option)
  const svg = chart.renderToSVGString()
  chart.dispose()
  return svg
}

describe('every chart draws with what is registered', () => {
  it.each(CASES)('%s', (type, data) => {
    const svg = draw(buildChartOption(data, type, { referenceValue: 10 }))
    expect(complaints).toEqual([])
    expect(svg).toMatch(DRAWN)
  })

  it('the sparkline on an indicator', () => {
    const svg = draw(
      buildSparkline([
        { t: '2026-10-20', v: 3 },
        { t: '2026-10-21', v: 5 },
      ] as never),
    )
    expect(complaints).toEqual([])
    expect(svg).toMatch(DRAWN)
  })
})
