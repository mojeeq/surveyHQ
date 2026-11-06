/**
 * An indicator's breakdown as lines of figures.
 *
 * Sixty bars in a tile the size of a postcard is a smear: the labels collide,
 * no figure can be quoted and a reader looking up one enumeration area has to
 * read every bar to find it. The same sixty groups as a table is a list
 * somebody can read down, and the tile can be set to either.
 *
 * Drawn from exactly the same numbers as the chart - the breakdown and the
 * per-group progress the tile already carries - so a reader comparing the two
 * forms of one widget finds no difference between them. It lives apart from
 * the widgets so it can be rendered on its own in a test, which the tile
 * cannot: that module reaches a map library that wants a browser.
 */
import { STATUS_COLORS } from "@/lib/charts";
import { formatNumber, formatValue } from "@/lib/format";
import type { BreakdownRow } from "@/lib/breakdown-order";

export function BreakdownTable({
  rows,
  variable,
  name,
  valueFormat,
  unit,
  lowerIsBetter,
  onSelect,
}: {
  rows: BreakdownRow[];
  /** The variable broken down by, which heads the first column. */
  variable: string;
  /** What is being counted, which heads the second. */
  name?: string;
  valueFormat?: string;
  unit?: string;
  lowerIsBetter?: boolean;
  /** Filter the page by one group, as clicking its bar does. */
  onSelect?: (variable: string, value: string) => void;
}) {
  // An indicator broken down for interest has no quotas at all, and two
  // columns of hyphens say nothing worth the width.
  const quoted = rows.some((row) => row.target !== null);

  return (
    <table className="w-full text-xs tabular-nums">
      <thead className="sticky top-0 bg-white/95 text-left text-ink-500 backdrop-blur dark:bg-dark-50/95 dark:text-dark-500">
        <tr>
          <th className="py-1 pr-2 font-medium">{variable || "Group"}</th>
          <th className="py-1 pr-2 text-right font-medium">{name || "Value"}</th>
          {quoted && (
            <>
              <th className="py-1 pr-2 text-right font-medium">Target</th>
              <th className="py-1 pr-2 text-right font-medium">
                {lowerIsBetter ? "Of limit" : "Done"}
              </th>
            </>
          )}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.group}
            className="border-t border-ink-100 dark:border-dark-200"
          >
            <td className="py-1 pr-2 text-ink-700 dark:text-dark-700">
              {onSelect ? (
                <button
                  className="text-left hover:underline"
                  onClick={() => onSelect(variable, row.group)}
                >
                  {row.group}
                </button>
              ) : (
                row.group
              )}
            </td>
            <td className="py-1 pr-2 text-right text-ink-800 dark:text-dark-800">
              {formatValue(row.value, valueFormat, unit)}
            </td>
            {quoted && (
              <>
                <td className="py-1 pr-2 text-right text-ink-500 dark:text-dark-500">
                  {row.target === null ? "-" : formatNumber(row.target)}
                </td>
                {/* A group with no quota of its own is not being judged, so it
                    carries no share and no colour rather than a nought. */}
                <td
                  className="py-1 pr-2 text-right font-medium"
                  style={{
                    color:
                      row.percent === null
                        ? undefined
                        : STATUS_COLORS[
                            row.status as keyof typeof STATUS_COLORS
                          ] ?? undefined,
                  }}
                >
                  {row.percent === null ? "-" : `${row.percent.toFixed(0)}%`}
                </td>
              </>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
