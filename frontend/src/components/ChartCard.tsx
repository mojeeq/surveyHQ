import ReactECharts from 'echarts-for-react'
import { useState } from 'react'
import { buildChartOption } from '@/lib/charts'
import { formatCell } from '@/lib/format'
import type { ChartType, QueryResult } from '@/lib/types'
import { EmptyState } from './ui'

/**
 * Renders a query result as a chart with a table fallback.
 *
 * The table toggle is not a nicety: three palette slots sit under 3:1 contrast
 * on white, and the accessibility rule is that such a chart must ship visible
 * labels or a table view. This is that table view.
 */
export default function ChartCard({
  result,
  chartType,
  height = 320,
  showToggle = true,
}: {
  result: QueryResult
  chartType: ChartType
  height?: number
  showToggle?: boolean
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')

  if (!result.rows.length) {
    return <EmptyState icon="◌" title="No data" description="This query returned no rows." />
  }

  if (chartType === 'table' || view === 'table') {
    return (
      <div className="flex flex-col">
        {showToggle && chartType !== 'table' && (
          <ViewToggle view={view} onChange={setView} />
        )}
        <div className="overflow-auto" style={{ maxHeight: height }}>
          <table className="table-base">
            <thead className="sticky top-0">
              <tr>
                {result.columns.map((column) => (
                  <th key={column.name}>{column.label || column.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
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
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      {showToggle && <ViewToggle view={view} onChange={setView} />}
      <ReactECharts
        option={buildChartOption(result, chartType)}
        style={{ height, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        notMerge
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
            view === option ? 'bg-ink-800 text-white' : 'text-ink-500 hover:bg-ink-100'
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  )
}
