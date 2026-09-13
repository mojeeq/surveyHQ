import ReactECharts from 'echarts-for-react'
import { useEffect, useRef, useState } from 'react'
import { buildChartOption, type BuildOptions } from '@/lib/charts'
import { formatCell, formatNumber } from '@/lib/format'
import type { ChartType, QueryResult } from '@/lib/types'
import { EmptyState } from './ui'

/**
 * Renders a query result as a chart with a table fallback.
 *
 * The table toggle is not a nicety: three palette slots sit under 3:1 contrast
 * on white, and the accessibility rule is that such a chart must ship visible
 * labels or a table view. This is that table view.
 */
/** The dimension value at one row of a result, for a mark that only knows its index. */
function categoryAt(result: QueryResult, index: number): string {
  const at = result.columns.findIndex((column) => column.type === 'dimension')
  if (at < 0) return ''
  const value = result.rows[index]?.[at]
  return value === null || value === undefined ? '' : String(value)
}

export default function ChartCard({
  result,
  chartType,
  height = 320,
  fill = false,
  showToggle = true,
  theme,
  display,
  onSelect,
}: {
  result: QueryResult
  chartType: ChartType
  height?: number
  /** Fill the parent instead of taking a fixed pixel height. Dashboard widgets
   *  are resizable, so a fixed height would leave the chart its original size
   *  inside a container the user just made bigger. */
  fill?: boolean
  showToggle?: boolean
  /** Categorical ordering, set per dashboard. */
  theme?: string
  /** How this chart is drawn: order, top-N, labels, a target line. */
  display?: BuildOptions
  /** Called with the category a click landed on, for filtering by it. */
  onSelect?: (category: string) => void
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const [filtering, setFiltering] = useState(false)
  // Kept by column position rather than by name: two measures can carry the
  // same label, and the position is what the row is indexed by anyway.
  const [columnFilters, setColumnFilters] = useState<Record<number, string>>({})
  const container = useRef<HTMLDivElement>(null)
  /** The drawn width, watched so long labels can be capped against it. */
  const [width, setWidth] = useState(0)
  const chart = useRef<ReactECharts>(null)

  // ECharts draws to a canvas sized in pixels at layout time and only listens
  // for *window* resizes. Dragging a dashboard widget's corner resizes the
  // container without ever resizing the window, so the canvas keeps its old
  // dimensions and the chart appears not to follow. Watch the element instead.
  useEffect(() => {
    const element = container.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      chart.current?.getEchartsInstance().resize()
      // How wide the chart is, for the one decision that cannot be made
      // without knowing: how much room a category name may take before it is
      // eating the plot it is labelling.
      setWidth(element.clientWidth)
    })
    observer.observe(element)
    setWidth(element.clientWidth)
    return () => observer.disconnect()
  }, [])

  if (!result.rows.length) {
    return <EmptyState icon="◌" title="No data" description="This query returned no rows." />
  }

  // A KPI is a mean of a 0/1 variable. Multiplying that mean by 100 is the
  // percentage coded 1, and the query engine applies the selected survey weight
  // before this renderer ever sees the value. With a grouping there is one row
  // per group, so the same component naturally becomes one KPI card per sex,
  // province, age band, or other dimension.
  if (chartType === 'kpi' && view === 'chart') {
    const dimensionIndexes = result.columns
      .map((column, index) => (column.type === 'dimension' ? index : -1))
      .filter((index) => index >= 0)
    const measureIndex = result.columns.findIndex((column) => column.type === 'measure')
    if (measureIndex < 0) {
      return <EmptyState icon="◌" title="No measure" description="This KPI has no value to display." />
    }
    const firstDimension = dimensionIndexes[0]
    const measure = result.columns[measureIndex]

    return (
      <div className={`flex flex-col ${fill ? 'h-full min-h-0' : ''}`}>
        {showToggle && <ViewToggle view={view} onChange={setView} />}
        <div
          className={`grid gap-3 ${result.rows.length > 1 ? 'sm:grid-cols-2 xl:grid-cols-3' : ''} ${
            fill ? 'min-h-0 flex-1 auto-rows-fr' : ''
          }`}
        >
          {result.rows.map((row, rowIndex) => {
            const raw = Number(row[measureIndex])
            const percentage = raw * 100
            const group = dimensionIndexes
              .map((index) => formatCell(row[index]))
              .filter(Boolean)
              .join(' · ')
            const selectable = Boolean(onSelect && firstDimension >= 0 && row[firstDimension] != null)
            return (
              <div
                key={rowIndex}
                className={`flex min-h-32 flex-col justify-center rounded-card border border-ink-200 bg-white p-5 dark:border-dark-300 dark:bg-dark-100 ${
                  selectable ? 'cursor-pointer hover:border-brand-400' : ''
                }`}
                onClick={
                  selectable
                    ? () => onSelect?.(String(row[firstDimension]))
                    : undefined
                }
              >
                <div className="text-4xl font-semibold tabular-nums tracking-tight text-ink-900 dark:text-dark-900">
                  {Number.isFinite(percentage)
                    ? `${formatNumber(percentage, display?.decimals ?? 1)}%`
                    : 'No value'}
                </div>
                <div className="mt-2 text-sm font-medium text-ink-600 dark:text-dark-600">
                  {group || 'Selected 1'}
                </div>
                {!group && (
                  <div className="mt-1 text-xs text-ink-400 dark:text-dark-500">
                    {measure.label || measure.name}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  if (chartType === 'table' || view === 'table') {
    const shown = filterRows(result.rows, result.columns, columnFilters)
    const narrowed = shown.length !== result.rows.length
    return (
      // `fill` is the dashboard asking for the widget's whole height. The
      // table used to ignore it and keep its own 320px ceiling, so a widget
      // dragged taller showed the same few rows with the rest of the card
      // empty beneath them - and a long table went on scrolling inside that
      // ceiling while half the widget stood unused. Filling means the rows
      // get the room, and resizing the widget does what it looks like it does.
      <div className={`flex flex-col ${fill ? 'h-full min-h-0' : ''}`}>
        <div className="flex shrink-0 items-center gap-2">
          {showToggle && chartType !== 'table' && (
            <ViewToggle view={view} onChange={setView} />
          )}
          <button
            className={`btn-ghost btn-sm ml-auto ${narrowed ? 'text-brand-700 dark:text-brand-400' : 'text-ink-500 dark:text-dark-500'}`}
            onClick={() => setFiltering(!filtering)}
            title="Narrow this table by its columns"
            aria-label="Filter columns"
            aria-pressed={filtering}
          >
            ⌕ {narrowed ? `${formatNumber(shown.length)} of ${formatNumber(result.rows.length)}` : 'Filter'}
          </button>
        </div>
        <div
          className={`overflow-auto ${fill ? 'min-h-0 flex-1' : ''}`}
          style={fill ? undefined : { maxHeight: height }}
        >
          <table className="table-base">
            <thead className="sticky top-0">
              <tr>
                {result.columns.map((column) => (
                  <th key={column.name}>{column.label || column.name}</th>
                ))}
              </tr>
              {/* A box under each heading, which is where people look for one.
                  Hidden until asked for: on a widget the size of a postcard a
                  permanent row of inputs is a quarter of the table gone. */}
              {filtering && (
                <tr>
                  {result.columns.map((column, index) => (
                    <th key={column.name} className="p-1">
                      <input
                        className="input h-6 w-full min-w-16 px-1 py-0 text-xs font-normal"
                        value={columnFilters[index] ?? ''}
                        placeholder={column.type === 'measure' ? '> 100' : 'contains…'}
                        aria-label={`Filter ${column.label || column.name}`}
                        onChange={(event) =>
                          setColumnFilters((current) => ({
                            ...current,
                            [index]: event.target.value,
                          }))
                        }
                      />
                    </th>
                  ))}
                </tr>
              )}
            </thead>
            <tbody>
              {shown.map((row, rowIndex) => (
                <tr
                  key={rowIndex}
                  className={onSelect ? 'cursor-pointer' : undefined}
                  onClick={
                    onSelect
                      ? () => {
                          // The first dimension column is what the row stands
                          // for, the same thing a bar stands for.
                          const at = result.columns.findIndex(
                            (column) => column.type === 'dimension',
                          )
                          const value = at >= 0 ? row[at] : null
                          if (value !== null && value !== undefined) {
                            onSelect(String(value))
                          }
                        }
                      : undefined
                  }
                >
                  {row.map((value, cellIndex) => (
                    <td
                      key={cellIndex}
                      className={
                        result.columns[cellIndex]?.type === 'measure'
                          ? 'text-right tabular-nums'
                          : ''
                      }
                    >
                      {formatCell(value)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {!shown.length && (
            <p className="px-2 py-6 text-center text-sm text-ink-400">
              No rows match these column filters.
            </p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div ref={container} className={`flex flex-col ${fill ? 'h-full min-h-0' : ''}`}>
      {showToggle && <ViewToggle view={view} onChange={setView} />}
      <ReactECharts
        ref={chart}
        option={buildChartOption(result, chartType, {
          ...display,
          theme,
          // A third of the chart, which leaves two thirds for the bars. Long
          // check names and long question labels otherwise push the plot into
          // a sliver at the right, and the bigger the text the worse it is.
          ...(width ? { maxLabelWidth: Math.round(width / 3) } : {}),
        })}
        style={fill ? { flex: 1, minHeight: 0, width: '100%' } : { height, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        notMerge
        onEvents={
          onSelect
            ? {
                // The category the mark stands for. Most types hand it over
                // as `name` - a pie slice, a bar, a point on a line. Two do
                // not: a scatter point is [x, y] and a heatmap cell is
                // [x, y, value], both with an empty name, so the category has
                // to be looked up by the index the click carries. Without that
                // those two silently did nothing.
                click: (params: {
                  name?: string
                  value?: unknown
                  dataIndex?: number
                }) => {
                  const byIndex =
                    typeof params?.dataIndex === 'number'
                      ? categoryAt(result, params.dataIndex)
                      : ''
                  const category =
                    params?.name ||
                    byIndex ||
                    (Array.isArray(params?.value) ? '' : String(params?.value ?? ''))
                  if (category) onSelect(category)
                },
                // On a pie the legend is where the category names are: the
                // slices themselves carry only a value and a percentage, so
                // the name is what the reader points at. ECharts reads a
                // click there as "hide this slice", so the one gesture that
                // names a category did nothing but make it disappear.
                //
                // Only for a pie. Every other chart's legend names its
                // series - measures, or the columns of a pivot - and
                // filtering the page by one of those would be filtering by
                // something that is not a category at all.
                ...(chartType === 'pie' || chartType === 'donut'
                  ? {
                      legendselectchanged: (
                        params: { name?: string },
                        instance: { dispatchAction: (action: object) => void },
                      ) => {
                        if (!params?.name) return
                        // Put the slice straight back: the click meant
                        // "show me this one", not "take it off the chart".
                        instance?.dispatchAction({
                          type: 'legendSelect',
                          name: params.name,
                        })
                        onSelect(params.name)
                      },
                    }
                  : {}),
              }
            : undefined
        }
        className={onSelect ? 'cursor-pointer' : undefined}
      />
    </div>
  )
}

function ViewToggle({
  view,
  onChange,
}: {
  view: 'chart' | 'table'
  onChange: (view: 'chart' | 'table') => void
}) {
  return (
    <div className="mb-2 flex justify-end gap-1">
      {(['chart', 'table'] as const).map((option) => (
        <button
          key={option}
          onClick={() => onChange(option)}
          className={`rounded px-2 py-1 text-xs font-medium capitalize transition-colors ${
            view === option
              ? 'bg-ink-800 text-white dark:bg-dark-300 dark:text-dark-900'
              : 'text-ink-500 hover:bg-ink-100 dark:text-dark-500 dark:hover:bg-dark-200'
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  )
}

/**
 * Narrow a table's rows by what was typed under each column.
 *
 * Text matches on what the cell reads as, which is what somebody scanning the
 * table is matching against too: type "North" against a coded column and the
 * label is what answers, not the code behind it.
 *
 * A number column also takes a comparison - "> 100", "<= 0" - because the
 * question asked of a measure is almost never "which of these contains a 7".
 */
function filterRows(
  rows: unknown[][],
  columns: { type?: string }[],
  filters: Record<number, string>,
): unknown[][] {
  const active = Object.entries(filters).filter(([, term]) => term.trim())
  if (!active.length) return rows

  return rows.filter((row) =>
    active.every(([index, term]) => {
      const at = Number(index)
      const value = row[at]
      const text = term.trim()
      const comparison = /^(>=|<=|>|<|=)\s*(-?[\d.]+)$/.exec(text)
      if (comparison && columns[at]?.type === 'measure') {
        const number = Number(value)
        if (!Number.isFinite(number)) return false
        const against = Number(comparison[2])
        switch (comparison[1]) {
          case '>':
            return number > against
          case '>=':
            return number >= against
          case '<':
            return number < against
          case '<=':
            return number <= against
          default:
            return number === against
        }
      }
      return formatCell(value).toLowerCase().includes(text.toLowerCase())
    }),
  )
}