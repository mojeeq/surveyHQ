import type { CrosstabResult } from '@/lib/types'
import { formatNumber } from '@/lib/format'
import { Badge } from './ui'

/**
 * A saved cross-tabulation, rendered the same way wherever it appears:
 * in the Explore builder and as a dashboard widget.
 */
export default function CrosstabTable({
  result,
  compact = false,
  maxHeight,
  fill = false,
  onSelect,
}: {
  result: CrosstabResult
  compact?: boolean
  maxHeight?: number
  /** Fill the parent rather than stopping at a fixed height. A dashboard widget
   *  is resizable, so a fixed cap leaves the table its original size inside a
   *  container the user has just made taller - the same fault charts had. */
  fill?: boolean
  /**
   * Filter the page by a heading that was clicked.
   *
   * A cross-tab has two variables rather than a chart's one, so which was
   * clicked has to travel with the value: a row heading means the row
   * variable, a column heading the column one. Body cells are deliberately
   * not clickable - a cell is the intersection of both, and filtering by two
   * things at once from one click is not what anybody expects from it.
   */
  onSelect?: (variable: string, value: string) => void
}) {
  const suffix = result.percentages === 'none' ? '' : '%'
  const showing = result.percentages !== 'none'
  const digits = showing ? 1 : 0
  // A column of percentages read down the page wants a constant width, so
  // 50% stays "50.0%" beside 48.2%. Counts do not: they are whole numbers.

  // A one-way table needs only one of the two total lines. The row total of a
  // single column is that column, and printing it beside itself is a column of
  // numbers that says nothing twice.
  // The question, not the column name. A corner reading "employment_status
  // sex" is the file talking; a reader wants "Employment status \ Sex". An
  // older saved cross-tab carries no labels, so the name is still the fallback.
  const rowName = result.row_variable_label || result.row_variable
  const columnName = result.column_variable_label || result.column_variable

  const showRowTotals = result.column_labels.length > 1
  const showColumnTotals = result.row_labels.length > 1

  return (
    <div className={`flex flex-col ${fill ? 'h-full min-h-0' : ''}`}>
      <div
        className={`overflow-auto rounded-card border border-ink-200 ${
          fill ? 'min-h-0 flex-1' : ''
        }`}
        style={!fill && maxHeight ? { maxHeight } : undefined}
      >
        <table className="table-base">
          <thead className="sticky top-0">
            <tr>
              <th className="sticky left-0 z-10 bg-ink-100 dark:bg-dark-200">
                {/* A one-way table has only one variable, so the corner names
                    that one rather than reading "region \ " with nothing
                    after the slash. The slash is escaped: in a template
                    literal a lone backslash before a space is dropped, so the
                    two names ran together separated by nothing but a gap. */}
                {rowName && columnName
                  ? `${rowName} \\ ${columnName}`
                  : rowName || columnName}
              </th>
              {result.column_labels.map((label) => (
                <th
                  key={label}
                  className={`text-right ${onSelect ? 'cursor-pointer hover:bg-ink-200' : ''}`}
                  onClick={
                    onSelect ? () => onSelect(result.column_variable, label) : undefined
                  }
                >
                  {label}
                </th>
              ))}
              {showRowTotals && <th className="text-right">Total</th>}
            </tr>
          </thead>
          <tbody>
            {result.row_labels.map((label, rowIndex) => (
              <tr key={label}>
                <td
                  className={`sticky left-0 bg-white font-medium dark:bg-dark-50 ${
                    onSelect ? 'cursor-pointer hover:bg-ink-50' : ''
                  }`}
                  onClick={onSelect ? () => onSelect(result.row_variable, label) : undefined}
                >
                  {label}
                </td>
                {result.values[rowIndex].map((value, cellIndex) => (
                  <td key={cellIndex} className="text-right tabular-nums">
                    {value === null ? '-' : `${formatNumber(value, digits, showing)}${suffix}`}
                  </td>
                ))}
                {showRowTotals && (
                  <td className="text-right font-semibold tabular-nums">
                    {formatNumber(result.row_totals[rowIndex])}
                  </td>
                )}
              </tr>
            ))}
            {showColumnTotals && (
              <tr className="bg-ink-50 font-semibold">
                <td className="sticky left-0 bg-ink-50 dark:bg-dark-100">Total</td>
                {result.column_totals.map((total, index) => (
                  <td key={index} className="text-right tabular-nums">
                    {formatNumber(total)}
                  </td>
                ))}
                {showRowTotals && (
                  <td className="text-right tabular-nums">
                    {formatNumber(result.grand_total)}
                  </td>
                )}
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {!compact && ((result.rows_omitted ?? 0) > 0 || (result.columns_omitted ?? 0) > 0) && (
        // A cut table still adds up, so nothing on screen would say the rest
        // is missing unless it says so here.
        <p className="mt-3 rounded-card border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Showing {formatNumber(result.row_labels.length)} of{' '}
          {formatNumber(result.row_labels.length + (result.rows_omitted ?? 0))} rows and{' '}
          {formatNumber(result.column_labels.length)} of{' '}
          {formatNumber(result.column_labels.length + (result.columns_omitted ?? 0))} columns.
          The totals cover what is shown.
        </p>
      )}

      {!compact && result.chi_square && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-500">
          <Badge tone="info">Chi-square</Badge>
          χ² = {result.chi_square.statistic.toFixed(3)}, df = {result.chi_square.dof},
          Cramér's V = {result.chi_square.cramers_v.toFixed(3)}
        </p>
      )}
    </div>
  )
}
