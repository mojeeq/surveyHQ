import { useMemo, useState, type UIEvent } from 'react'
import { formatCell } from '@/lib/format'
import { EmptyState } from './ui'

const ROW_HEIGHT = 34
const OVERSCAN = 12
const VIRTUALISE_ABOVE = 200

/** Generic scrollable table for raw rows and query results.
 *
 * Large analysis results used to create one DOM row per result (up to 100k).
 * Windowing keeps the same table semantics but only mounts the rows around the
 * viewport, which makes scrolling and initial rendering effectively constant.
 */
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
  const [scrollTop, setScrollTop] = useState(0)
  const numeric = useMemo(() => new Set(numericColumns), [numericColumns])
  if (!rows.length) return <EmptyState icon="◌" title={emptyLabel} />

  const virtual = rows.length > VIRTUALISE_ABOVE
  const visibleCount = Math.ceil(maxHeight / ROW_HEIGHT) + OVERSCAN * 2
  const start = virtual
    ? Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN)
    : 0
  const end = virtual ? Math.min(rows.length, start + visibleCount) : rows.length
  const visibleRows = virtual ? rows.slice(start, end) : rows
  const topSpacer = virtual ? start * ROW_HEIGHT : 0
  const bottomSpacer = virtual ? (rows.length - end) * ROW_HEIGHT : 0

  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    if (virtual) setScrollTop(event.currentTarget.scrollTop)
  }

  return (
    <div
      className="overflow-auto rounded-card border border-ink-200 dark:border-dark-200"
      style={{ maxHeight }}
      onScroll={onScroll}
    >
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
          {topSpacer > 0 && (
            <tr aria-hidden="true">
              <td colSpan={columns.length + 1} style={{ height: topSpacer, padding: 0, border: 0 }} />
            </tr>
          )}
          {visibleRows.map((row, visibleIndex) => {
            const rowIndex = start + visibleIndex
            return (
              <tr key={rowIndex} style={virtual ? { height: ROW_HEIGHT } : undefined}>
                <td className="text-right text-xs text-ink-400 tabular-nums dark:text-dark-400">
                  {rowIndex + 1}
                </td>
                {row.map((value, cellIndex) => (
                  <td
                    key={cellIndex}
                    className={
                      numeric.has(cellIndex) || typeof value === 'number'
                        ? 'text-right tabular-nums'
                        : 'max-w-xs truncate'
                    }
                    title={value === null ? '' : String(value)}
                  >
                    {formatCell(value)}
                  </td>
                ))}
              </tr>
            )
          })}
          {bottomSpacer > 0 && (
            <tr aria-hidden="true">
              <td colSpan={columns.length + 1} style={{ height: bottomSpacer, padding: 0, border: 0 }} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
