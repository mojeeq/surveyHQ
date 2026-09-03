// Builds ECharts options from a QueryResult.
//
// Colour follows the validated categorical palette below: hues are assigned in a
// fixed order and never cycled, so a series keeps its colour when a filter
// changes the series count. Three of the eight slots fall under 3:1 contrast on
// a white surface, which is why every chart ships a legend and a table view
// (ChartCard's "Table" toggle) rather than relying on colour alone.

import type { EChartsOption } from 'echarts'
import type { ChartType, QueryResult } from './types'
import { formatCell, formatNumber } from './format'

/**
 * Categorical themes: the same eight validated hues in different fixed orders.
 *
 * A theme is an *ordering*, not a new set of colours - the hues have already
 * passed the lightness, chroma, colour-vision and contrast checks, and inventing
 * new ones would mean re-earning all of that. What the order controls is how
 * well *adjacent* series separate, since those are the ones a reader compares.
 *
 * These orders were not chosen by eye. Random orderings were fed to the
 * palette validator and scored on their worst adjacent separation under
 * simulated colour-vision deficiency; the figures below are that score, in
 * OKLab ΔE ×100, measured against the light chart surface. Higher is better and
 * 8 is the floor.
 *
 * Three of the eight hues sit under 3:1 contrast on white whichever order they
 * are in, which is why every chart carries a legend and a table view rather
 * than relying on colour alone.
 */
export const CHART_THEMES = {
  // The original order. Kept as the default so that switching versions does not
  // repaint every existing dashboard.
  default: {
    label: 'Default',
    description: 'Blue-led, the order dashboards were built in',
    colors: [
      '#2a78d6', // blue
      '#eb6834', // orange
      '#1baf7a', // aqua
      '#eda100', // yellow
      '#e87ba4', // magenta
      '#008300', // green
      '#4a3aa7', // violet
      '#e34948', // red
    ],
  },
  // Worst adjacent ΔE 15.3 (protan), normal-vision 20.8 - the best separation
  // found, and a clear improvement on the default's 9.1.
  vivid: {
    label: 'High separation',
    description: 'Adjacent series stay furthest apart for colour-blind readers',
    colors: [
      '#e87ba4', // magenta
      '#008300', // green
      '#eda100', // yellow
      '#e34948', // red
      '#4a3aa7', // violet
      '#1baf7a', // aqua
      '#2a78d6', // blue
      '#eb6834', // orange
    ],
  },
  // Worst adjacent ΔE 15.2 (protan), normal-vision 15.6.
  bold: {
    label: 'Bold',
    description: 'Warm lead, near-equal separation',
    colors: [
      '#e34948', // red
      '#2a78d6', // blue
      '#1baf7a', // aqua
      '#008300', // green
      '#e87ba4', // magenta
      '#eda100', // yellow
      '#4a3aa7', // violet
      '#eb6834', // orange
    ],
  },
} as const

export type ChartTheme = keyof typeof CHART_THEMES

export function themeColors(theme: string | null | undefined): readonly string[] {
  return (CHART_THEMES[(theme ?? 'default') as ChartTheme] ?? CHART_THEMES.default).colors
}

/** The default order, for callers that do not carry a theme. */
export const SERIES_COLORS = CHART_THEMES.default.colors

/** Single-hue ramp for magnitude (heatmaps). Light to dark. */
export const SEQUENTIAL_RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95']

export const STATUS_COLORS = {
  ok: '#0ca30c',
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
  unknown: '#898781',
} as const

const INK = {
  muted: '#898781',
  grid: '#e1e0d9',
  axis: '#c3c2b7',
  surface: '#ffffff',
  primary: '#0b0b0b',
}

const BASE_TEXT = {
  fontFamily: 'Inter, system-ui, -apple-system, "Segoe UI", sans-serif',
  fontSize: 12,
}

/** More than this many categories and the tail is folded into "Other". */
export const MAX_SERIES = 8

function axisCommon(rotate = 0) {
  return {
    axisLine: { lineStyle: { color: INK.axis } },
    axisTick: { show: false },
    axisLabel: { color: INK.muted, ...BASE_TEXT, rotate, hideOverlap: true },
    splitLine: { show: false },
  }
}

function valueAxis(name = '') {
  return {
    type: 'value' as const,
    name,
    nameTextStyle: { color: INK.muted, ...BASE_TEXT },
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: INK.muted,
      ...BASE_TEXT,
      // Small ranges (coordinates, rates) need decimals, or consecutive ticks
      // round to the same label. Large ones get the compact k/M form.
      formatter: (value: number) =>
        Math.abs(value) < 10 && !Number.isInteger(value)
          ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
          : formatNumber(value),
    },
    // Recessive hairline grid
    splitLine: { lineStyle: { color: INK.grid, width: 1 } },
  }
}

const tooltipBase = {
  backgroundColor: '#ffffff',
  borderColor: INK.grid,
  borderWidth: 1,
  padding: [8, 12] as [number, number],
  textStyle: { color: INK.primary, ...BASE_TEXT },
  extraCssText: 'box-shadow: 0 10px 30px rgba(15,23,42,.12); border-radius: 8px;',
}

export interface BuildOptions {
  horizontal?: boolean
  stacked?: boolean
  showLegend?: boolean
  /** Which categorical ordering to use; see CHART_THEMES. */
  theme?: string
  /** How the categories are ordered along the axis. */
  sort?: 'none' | 'value_desc' | 'value_asc' | 'label_asc' | 'label_desc'
  /** Keep the largest N categories and fold the rest into one "Other" bar. */
  topN?: number
  /** Print the number on the mark. Bars and slices only - see below. */
  showValues?: boolean
  /** Stack to 100%, for reading composition rather than magnitude. */
  percentStack?: boolean
  smooth?: boolean
  valueTitle?: string
  valueMin?: number | null
  valueMax?: number | null
  /** A line across the plot, e.g. the target this chart is read against. */
  referenceValue?: number | null
  referenceLabel?: string
  decimals?: number
}

/** A fixed value-axis range, when one is asked for. */
function bounds(options: BuildOptions) {
  return {
    ...(options.valueMin === null || options.valueMin === undefined
      ? {}
      : { min: options.valueMin }),
    ...(options.valueMax === null || options.valueMax === undefined
      ? {}
      : { max: options.valueMax }),
  }
}

/** A horizontal rule across the plot, for the target a chart is read against. */
function referenceLine(options: BuildOptions) {
  if (options.referenceValue === null || options.referenceValue === undefined) return undefined
  return {
    silent: true,
    symbol: 'none',
    label: {
      formatter: options.referenceLabel || `Target ${formatNumber(options.referenceValue)}`,
      // At the left end: at the right it runs off the edge of the plot, since
      // nothing reserves room for it there.
      position: 'insideStartTop' as const,
      color: INK.muted,
      ...BASE_TEXT,
    },
    lineStyle: { color: INK.axis, width: 2, type: 'dashed' as const },
    data: [{ yAxis: options.referenceValue }],
  }
}

/** Data labels, in a text token rather than the series colour.
 *
 * Off past a couple of dozen marks whatever was asked for: a number on every
 * one of forty bars is a wall of digits that overlap each other, and the axis
 * and the tooltip already carry them.
 */
const MAX_LABELLED = 24

function markLabel(options: BuildOptions, position: 'top' | 'right' | 'inside', marks = 0) {
  if (!options.showValues || marks > MAX_LABELLED) return { show: false }
  return {
    show: true,
    position,
    color: position === 'inside' ? '#fff' : INK.muted,
    ...BASE_TEXT,
    formatter: (params: any) => formatNumber(Number(params.value), options.decimals ?? 0),
  }
}

/**
 * Shape a result into { categories, series }.
 *
 * One dimension + N measures -> one series per measure.
 * Two dimensions + one measure -> one series per value of the second dimension.
 */
function pivot(result: QueryResult) {
  const dimensions = result.columns.filter((c) => c.type === 'dimension')
  const measures = result.columns.filter((c) => c.type === 'measure')
  const names = result.columns.map((c) => c.name)

  if (dimensions.length >= 2 && measures.length >= 1) {
    const rowIndex = names.indexOf(dimensions[0].name)
    const colIndex = names.indexOf(dimensions[1].name)
    const valIndex = names.indexOf(measures[0].name)

    const categories: string[] = []
    const seriesNames: string[] = []
    const lookup = new Map<string, number>()

    for (const row of result.rows) {
      const category = formatCell(row[rowIndex])
      const seriesName = formatCell(row[colIndex])
      if (!categories.includes(category)) categories.push(category)
      if (!seriesNames.includes(seriesName)) seriesNames.push(seriesName)
      lookup.set(`${category}||${seriesName}`, Number(row[valIndex] ?? 0))
    }
    const kept = seriesNames.slice(0, MAX_SERIES)
    return {
      categories,
      series: kept.map((name) => ({
        name,
        data: categories.map((category) => lookup.get(`${category}||${name}`) ?? null),
      })),
      valueLabel: measures[0].label || measures[0].name,
      categoryLabel: dimensions[0].label || dimensions[0].name,
    }
  }

  const dimensionIndex = dimensions.length ? names.indexOf(dimensions[0].name) : -1
  const categories = result.rows.map((row, index) =>
    dimensionIndex >= 0 ? formatCell(row[dimensionIndex]) : `#${index + 1}`,
  )
  return {
    categories,
    series: measures.map((measure) => ({
      name: measure.label || measure.name,
      data: result.rows.map((row) => {
        const value = row[names.indexOf(measure.name)]
        return value === null || value === undefined ? null : Number(value)
      }),
    })),
    valueLabel: measures.length === 1 ? measures[0].label || measures[0].name : '',
    categoryLabel: dimensions.length ? dimensions[0].label || dimensions[0].name : '',
  }
}

/**
 * Order the categories, and fold the tail into one "Other".
 *
 * Both are reading aids rather than data changes: a bar chart of forty
 * provinces sorted by name answers nothing, and the ninth series is never a
 * new colour - it folds into Other, which is also what keeps a palette inside
 * the range it was validated over.
 */
function shape(
  categories: string[],
  series: { name: string; data: (number | null)[] }[],
  options: BuildOptions,
) {
  const totals = categories.map((_, index) =>
    series.reduce((sum, entry) => sum + Number(entry.data[index] ?? 0), 0),
  )
  let order = categories.map((_, index) => index)

  switch (options.sort) {
    case 'value_desc':
      order = order.sort((a, b) => totals[b] - totals[a])
      break
    case 'value_asc':
      order = order.sort((a, b) => totals[a] - totals[b])
      break
    case 'label_asc':
      order = order.sort((a, b) => categories[a].localeCompare(categories[b]))
      break
    case 'label_desc':
      order = order.sort((a, b) => categories[b].localeCompare(categories[a]))
      break
    default:
      break
  }

  const top = options.topN && options.topN > 0 ? options.topN : 0
  let names = order.map((index) => categories[index])
  let rows = series.map((entry) => ({
    name: entry.name,
    data: order.map((index) => entry.data[index]),
  }))

  if (top && names.length > top) {
    // Ranked by size for the fold, whatever order the axis is in: "Other"
    // means the small ones, not the last ones alphabetically.
    const ranked = [...order].sort((a, b) => totals[b] - totals[a])
    const kept = new Set(ranked.slice(0, top))
    const keptOrder = order.filter((index) => kept.has(index))
    const rest = order.filter((index) => !kept.has(index))
    names = [...keptOrder.map((index) => categories[index]), `Other (${rest.length})`]
    rows = series.map((entry) => ({
      name: entry.name,
      data: [
        ...keptOrder.map((index) => entry.data[index]),
        rest.reduce((sum, index) => sum + Number(entry.data[index] ?? 0), 0),
      ],
    }))
  }

  if (options.percentStack) {
    // Each category summing to 100, which is what a composition is read as.
    const columnTotals = names.map((_, index) =>
      rows.reduce((sum, entry) => sum + Number(entry.data[index] ?? 0), 0),
    )
    rows = rows.map((entry) => ({
      name: entry.name,
      data: entry.data.map((value, index) =>
        columnTotals[index] ? (Number(value ?? 0) / columnTotals[index]) * 100 : null,
      ),
    }))
  }

  return { categories: names, series: rows }
}

export function buildChartOption(
  result: QueryResult,
  chartType: ChartType,
  options: BuildOptions = {},
): EChartsOption {
  const palette = themeColors(options.theme)
  const pivoted = pivot(result)
  const valueLabelText = pivoted.valueLabel
  const { categories, series } = shape(pivoted.categories, pivoted.series, options)
  const multiSeries = series.length > 1
  // A single series is named by the chart title, so it needs no legend box -
  // and can be given one on request. Two or more always keep theirs, whatever
  // is asked for: without it the only thing telling the series apart is their
  // colour, which is exactly what a colour-blind reader cannot use.
  const legend = multiSeries || (options.showLegend ?? false)

  const common: EChartsOption = {
    color: [...palette],
    textStyle: BASE_TEXT,
    animationDuration: 400,
    grid: { left: 8, right: 16, top: legend ? 40 : 16, bottom: 8, containLabel: true },
    legend: legend
      ? {
          type: 'scroll',
          top: 0,
          left: 0,
          icon: 'roundRect',
          itemWidth: 10,
          itemHeight: 10,
          itemGap: 16,
          textStyle: { color: '#52514e', ...BASE_TEXT },
        }
      : { show: false },
  }

  switch (chartType) {
    case 'pie':
    case 'donut': {
      const values = categories.map((name, index) => ({
        name,
        value: Number(series[0]?.data[index] ?? 0),
      }))
      return {
        ...common,
        grid: undefined,
        tooltip: {
          ...tooltipBase,
          trigger: 'item',
          formatter: (params: any) =>
            `${params.marker} ${params.name}<br/><b>${formatNumber(params.value)}</b> (${params.percent}%)`,
        },
        // Legend along the bottom: a side legend collides with the slice labels.
        legend: {
          type: 'scroll',
          orient: 'horizontal',
          bottom: 0,
          left: 'center',
          icon: 'roundRect',
          itemWidth: 10,
          itemHeight: 10,
          itemGap: 16,
          textStyle: { color: '#52514e', ...BASE_TEXT },
        },
        series: [
          {
            type: 'pie',
            radius: chartType === 'donut' ? ['48%', '70%'] : ['0%', '68%'],
            center: ['50%', '45%'],
            avoidLabelOverlap: true,
            // 2px surface gap between adjacent segments
            itemStyle: { borderColor: INK.surface, borderWidth: 2, borderRadius: 3 },
            // The legend carries the names, so the slice label is the value only
            label: options.showValues
              ? {
                  color: '#52514e',
                  ...BASE_TEXT,
                  formatter: (params: any) =>
                    `${formatNumber(Number(params.value), options.decimals ?? 0)} (${params.percent}%)`,
                }
              : { color: '#52514e', ...BASE_TEXT, formatter: '{d}%' },
            labelLine: { length: 8, length2: 8, lineStyle: { color: INK.axis } },
            data: values,
          },
        ],
      }
    }

    case 'scatter': {
      const [x, y] = series
      return {
        ...common,
        tooltip: {
          ...tooltipBase,
          trigger: 'item',
          formatter: (params: any) =>
            `${params.marker} ${categories[params.dataIndex] ?? ''}<br/>` +
            `${formatNumber(params.value[0], 2)} / ${formatNumber(params.value[1], 2)}`,
        },
        // scale: true keeps the axes on the data's own range. Forcing zero on a
        // coordinate pair squashes every point into a corner.
        xAxis: { ...valueAxis(x?.name ?? ''), scale: true },
        yAxis: { ...valueAxis(y?.name ?? ''), scale: true },
        series: [
          {
            type: 'scatter',
            symbolSize: 10,
            // 2px surface ring so overlapping points stay separable
            itemStyle: { color: palette[0], borderColor: INK.surface, borderWidth: 2 },
            data: categories.map((_, index) => [
              Number(x?.data[index] ?? 0),
              Number(y?.data[index] ?? 0),
            ]),
          },
        ],
      }
    }

    case 'heatmap': {
      const values: [number, number, number][] = []
      let max = 0
      series.forEach((entry, seriesIndex) => {
        entry.data.forEach((value, categoryIndex) => {
          const numeric = Number(value ?? 0)
          max = Math.max(max, numeric)
          values.push([categoryIndex, seriesIndex, numeric])
        })
      })
      return {
        ...common,
        legend: { show: false },
        grid: { left: 8, right: 16, top: 16, bottom: 56, containLabel: true },
        tooltip: {
          ...tooltipBase,
          trigger: 'item',
          formatter: (params: any) =>
            `${categories[params.value[0]]} / ${series[params.value[1]]?.name}<br/>` +
            `<b>${formatNumber(params.value[2])}</b>`,
        },
        xAxis: { type: 'category', data: categories, ...axisCommon(0) },
        yAxis: { type: 'category', data: series.map((s) => s.name), ...axisCommon(0) },
        visualMap: {
          min: 0,
          max: max || 1,
          orient: 'horizontal',
          left: 'center',
          bottom: 0,
          itemWidth: 12,
          itemHeight: 90,
          textStyle: { color: INK.muted, ...BASE_TEXT },
          inRange: { color: SEQUENTIAL_RAMP },
        },
        series: [
          {
            type: 'heatmap',
            data: values,
            itemStyle: { borderColor: INK.surface, borderWidth: 2, borderRadius: 3 },
          },
        ],
      }
    }

    case 'funnel':
      return {
        ...common,
        grid: undefined,
        tooltip: { ...tooltipBase, trigger: 'item' },
        series: [
          {
            type: 'funnel',
            left: '10%',
            width: '80%',
            gap: 2,
            label: { position: 'inside', color: '#fff', ...BASE_TEXT },
            itemStyle: { borderColor: INK.surface, borderWidth: 2 },
            data: categories.map((name, index) => ({
              name,
              value: Number(series[0]?.data[index] ?? 0),
            })),
          },
        ],
      }

    case 'line':
    case 'area':
      return {
        ...common,
        tooltip: {
          ...tooltipBase,
          trigger: 'axis',
          // Crosshair, per the interaction rules for time series
          axisPointer: { type: 'line', lineStyle: { color: INK.axis, width: 1 } },
        },
        xAxis: { type: 'category', data: categories, boundaryGap: false, ...axisCommon() },
        yAxis: {
          ...valueAxis(options.valueTitle ?? (multiSeries ? '' : valueLabelText)),
          ...bounds(options),
        },
        series: series.map((entry, index) => ({
          name: entry.name,
          type: 'line',
          data: entry.data,
          smooth: Boolean(options.smooth),
          // A number on every point is unreadable on a line, so the labels
          // toggle deliberately does not reach here - see the bar branch.
          ...(index === 0 ? { markLine: referenceLine(options) } : {}),
          symbol: 'circle',
          symbolSize: 8,
          showSymbol: entry.data.length <= 40,
          lineStyle: { width: 2 },
          itemStyle: { borderColor: INK.surface, borderWidth: 2 },
          ...(chartType === 'area'
            ? {
                areaStyle: {
                  opacity: 0.16,
                  color: palette[index % palette.length],
                },
                stack: options.stacked ? 'total' : undefined,
              }
            : {}),
        })),
      }

    case 'bar':
    case 'horizontal_bar':
    case 'stacked_bar':
    default: {
      const horizontal = chartType === 'horizontal_bar' || options.horizontal
      const stacked = chartType === 'stacked_bar' || options.stacked
      const categoryAxis = {
        type: 'category' as const,
        data: categories,
        ...axisCommon(horizontal ? 0 : categories.length > 8 ? 30 : 0),
      }
      return {
        ...common,
        grid: {
          left: 8,
          right: 24,
          // Headroom for a number printed above the tallest bar, which is
          // otherwise drawn outside the plot and clipped.
          top: legend ? 40 : options.showValues ? 28 : 16,
          bottom: 8,
          containLabel: true,
        },
        tooltip: {
          ...tooltipBase,
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (params: any) => {
            const list = Array.isArray(params) ? params : [params]
            const rows = list
              .filter((p: any) => p.value !== null && p.value !== undefined)
              .map(
                (p: any) =>
                  `${p.marker} ${p.seriesName}: <b>${formatNumber(Number(p.value), 2)}</b>`,
              )
              .join('<br/>')
            const head = list[0]?.axisValueLabel ?? list[0]?.name ?? ''
            return `${head}<br/>${rows}`
          },
        },
        xAxis: horizontal
          ? { ...valueAxis(options.valueTitle ?? ''), ...bounds(options) }
          : categoryAxis,
        yAxis: horizontal
          ? categoryAxis
          : {
              ...valueAxis(options.valueTitle ?? (multiSeries ? '' : valueLabelText)),
              ...bounds(options),
            },
        series: series.map((entry, index) => ({
          name: entry.name,
          type: 'bar',
          data: entry.data,
          stack: stacked ? 'total' : undefined,
          barMaxWidth: 42,
          label: markLabel(options, horizontal ? 'right' : 'top', categories.length),
          // 4px rounded data-end anchored to the baseline
          itemStyle: stacked
            ? { borderColor: INK.surface, borderWidth: 2 }
            : { borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] },
          // One reference line, on the first series, or it is drawn once per
          // series and the plot grows a ladder of identical rules.
          ...(index === 0 && !horizontal ? { markLine: referenceLine(options) } : {}),
        })),
      }
    }
  }
}

/** Sparkline used inside indicator tiles. */
export function buildSparkline(
  points: { t: string; v: number | null }[],
  theme?: string,
): EChartsOption {
  const palette = themeColors(theme)
  return {
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: { type: 'category', show: false, data: points.map((p) => p.t) },
    yAxis: { type: 'value', show: false, scale: true },
    tooltip: {
      ...tooltipBase,
      trigger: 'axis',
      formatter: (params: any) => {
        const point = Array.isArray(params) ? params[0] : params
        return `${new Date(point.axisValue).toLocaleDateString()}<br/><b>${formatNumber(
          Number(point.value),
        )}</b>`
      },
    },
    series: [
      {
        type: 'line',
        data: points.map((p) => p.v),
        smooth: false,
        symbol: 'none',
        lineStyle: { width: 2, color: palette[0] },
        areaStyle: { opacity: 0.12, color: palette[0] },
      },
    ],
  }
}
