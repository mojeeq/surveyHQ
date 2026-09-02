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

/** Fixed categorical order - validated for colour-vision deficiency separation. */
export const SERIES_COLORS = [
  '#2a78d6', // blue
  '#eb6834', // orange
  '#1baf7a', // aqua
  '#eda100', // yellow
  '#e87ba4', // magenta
  '#008300', // green
  '#4a3aa7', // violet
  '#e34948', // red
]

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
      formatter: (value: number) => formatNumber(value),
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

interface BuildOptions {
  horizontal?: boolean
  stacked?: boolean
  showLegend?: boolean
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

export function buildChartOption(
  result: QueryResult,
  chartType: ChartType,
  options: BuildOptions = {},
): EChartsOption {
  const { categories, series, valueLabel } = pivot(result)
  const multiSeries = series.length > 1
  // A single series is named by the chart title, so it needs no legend box.
  const legend = options.showLegend ?? multiSeries

  const common: EChartsOption = {
    color: SERIES_COLORS,
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
        legend: {
          type: 'scroll',
          orient: 'vertical',
          right: 0,
          top: 'middle',
          icon: 'roundRect',
          itemWidth: 10,
          itemHeight: 10,
          textStyle: { color: '#52514e', ...BASE_TEXT },
        },
        series: [
          {
            type: 'pie',
            radius: chartType === 'donut' ? ['52%', '76%'] : ['0%', '74%'],
            center: ['38%', '50%'],
            avoidLabelOverlap: true,
            // 2px surface gap between adjacent segments
            itemStyle: { borderColor: INK.surface, borderWidth: 2, borderRadius: 3 },
            label: { color: '#52514e', ...BASE_TEXT, formatter: '{b}: {d}%' },
            labelLine: { lineStyle: { color: INK.axis } },
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
        xAxis: { ...valueAxis(x?.name ?? '') },
        yAxis: valueAxis(y?.name ?? ''),
        series: [
          {
            type: 'scatter',
            symbolSize: 10,
            // 2px surface ring so overlapping points stay separable
            itemStyle: { color: SERIES_COLORS[0], borderColor: INK.surface, borderWidth: 2 },
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
        yAxis: valueAxis(multiSeries ? '' : valueLabel),
        series: series.map((entry, index) => ({
          name: entry.name,
          type: 'line',
          data: entry.data,
          smooth: false,
          symbol: 'circle',
          symbolSize: 8,
          showSymbol: entry.data.length <= 40,
          lineStyle: { width: 2 },
          itemStyle: { borderColor: INK.surface, borderWidth: 2 },
          ...(chartType === 'area'
            ? {
                areaStyle: {
                  opacity: 0.16,
                  color: SERIES_COLORS[index % SERIES_COLORS.length],
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
          top: legend ? 40 : 16,
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
        xAxis: horizontal ? valueAxis() : categoryAxis,
        yAxis: horizontal ? categoryAxis : valueAxis(multiSeries ? '' : valueLabel),
        series: series.map((entry) => ({
          name: entry.name,
          type: 'bar',
          data: entry.data,
          stack: stacked ? 'total' : undefined,
          barMaxWidth: 42,
          // 4px rounded data-end anchored to the baseline
          itemStyle: stacked
            ? { borderColor: INK.surface, borderWidth: 2 }
            : { borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] },
        })),
      }
    }
  }
}

/** Sparkline used inside indicator tiles. */
export function buildSparkline(points: { t: string; v: number | null }[]): EChartsOption {
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
        lineStyle: { width: 2, color: SERIES_COLORS[0] },
        areaStyle: { opacity: 0.12, color: SERIES_COLORS[0] },
      },
    ],
  }
}
