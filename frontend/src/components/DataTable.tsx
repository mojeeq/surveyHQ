import { formatCell } from '@/lib/format'
import { EmptyState } from './ui'

/** Generic scrollable table for raw rows and query results. */
export default function DataTable({
  columns,
  rows,
  numericColumns = [],
  maxHeight = 520,
  emptyLabel = 'No rows to show',
}: {
  columns: string[]
  rows: unknown[][]
  numericColumns?: number[]
  maxHeight?: number
  emptyLabel?: string
}) {
  if (!rows.length) return <EmptyState icon="◌" title={emptyLabel} />
  return (
    <div className="overflow-auto rounded-card border border-ink-200" style={{ maxHeight }}>
      <table className="table-base">
        <thead className="sticky top-0 z-10">
          <tr>
            <th className="w-12 text-right">#</th>
            {columns.map((column) => (
              <th key={column} title={column}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              <td className="text-right text-xs text-ink-400 tabular-nums">{rowIndex + 1}</td>
              {row.map((value, cellIndex) => (
                <td
                  key={cellIndex}
                  className={
                    numericColumns.includes(cellIndex) || typeof value === 'number'
                      ? 'text-right tabular-nums'
                      : 'max-w-xs truncate'
                  }
                  title={value === null ? '' : String(value)}
                >
                  {formatCell(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
