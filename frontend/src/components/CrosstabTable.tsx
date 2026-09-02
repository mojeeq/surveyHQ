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
}: {
  result: CrosstabResult
  compact?: boolean
  maxHeight?: number
}) {
  const suffix = result.percentages === 'none' ? '' : '%'
  const showing = result.percentages !== 'none'
  const digits = showing ? 1 : 0
  // A column of percentages read down the page wants a constant width, so
  // 50% stays "50.0%" beside 48.2%. Counts do not: they are whole numbers.

  return (
    <div className="flex flex-col">
      <div
        className="overflow-auto rounded-lg border border-ink-200"
        style={maxHeight ? { maxHeight } : undefined}
      >
        <table className="table-base">
          <thead className="sticky top-0">
            <tr>
              <th className="sticky left-0 z-10 bg-ink-100">
                {result.row_variable} \ {result.column_variable}
              </th>
              {result.column_labels.map((label) => (
                <th key={label} className="text-right">
                  {label}
                </th>
              ))}
              <th className="text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {result.row_labels.map((label, rowIndex) => (
              <tr key={label}>
                <td className="sticky left-0 bg-white font-medium">{label}</td>
                {result.values[rowIndex].map((value, cellIndex) => (
                  <td key={cellIndex} className="text-right tabular-nums">
                    {value === null ? '–' : `${formatNumber(value, digits, showing)}${suffix}`}
                  </td>
                ))}
                <td className="text-right font-semibold tabular-nums">
                  {formatNumber(result.row_totals[rowIndex])}
                </td>
              </tr>
            ))}
            <tr className="bg-ink-50 font-semibold">
              <td className="sticky left-0 bg-ink-50">Total</td>
              {result.column_totals.map((total, index) => (
                <td key={index} className="text-right tabular-nums">
                  {formatNumber(total)}
                </td>
              ))}
              <td className="text-right tabular-nums">{formatNumber(result.grand_total)}</td>
            </tr>
          </tbody>
        </table>
      </div>

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
