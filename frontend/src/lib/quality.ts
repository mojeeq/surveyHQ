/**
 * What a data quality panel plots, and in what order.
 *
 * Pure: the numbers a panel of checks is drawn from, shaped into results, and
 * the small vocabulary of which charts each of its views may be drawn as. It
 * sits apart from the widget that renders it so that it can be read - and
 * tested - without a browser: the widget file reaches Leaflet through the map,
 * and importing that outside one is how a test of an ordering rule ends up
 * failing on `window is not defined`.
 */
import { STATUS_COLORS } from "@/lib/charts";

import type { ChartType, QueryResult } from "@/lib/types";

/** What a check's bar is coloured by: its finding, not its position. */
export const CHECK_COLOURS: Record<string, string> = {
  failing: STATUS_COLORS.critical,
  passing: STATUS_COLORS.ok,
  "not run": STATUS_COLORS.unknown,
};

export const checkState = (check: any) =>
  check.passed === false ? "failing" : check.passed ? "passing" : "not run";

/**
 * How a quality panel may be drawn, by what it is plotting.
 *
 * Not the whole chart menu. A pie of failure rates would be a pie of numbers
 * that are not parts of anything - three checks at 40% are not 120% of a whole
 * - so the shares are offered only where the parts really are parts, which is
 * the count of rows each check flagged out of all the rows flagged. The first
 * entry for a view is what that view draws when nothing was chosen, so the
 * panels built before this existed keep the chart they have always had.
 */
export const QUALITY_CHARTS: Record<
  string,
  { value: ChartType; label: string }[]
> = {
  rate: [
    { value: "horizontal_bar", label: "Horizontal bars" },
    { value: "bar", label: "Columns" },
    { value: "table", label: "Table" },
  ],
  rows: [
    { value: "horizontal_bar", label: "Horizontal bars" },
    { value: "bar", label: "Columns" },
    { value: "donut", label: "Donut" },
    { value: "pie", label: "Pie" },
    { value: "table", label: "Table" },
  ],
  trend: [
    { value: "line", label: "Line" },
    { value: "area", label: "Area" },
    { value: "table", label: "Table" },
  ],
};

/**
 * The chart a panel is drawn as: what was chosen, if the view still offers it.
 *
 * A view and a chart are stored separately, so a panel saved as a donut of
 * rows flagged and then switched to failure rates is holding a pair that was
 * never on the menu. Falling back to the view's own default draws something
 * honest instead of leaving the widget blank.
 */
export function qualityChartType(view: string, chosen?: string): ChartType {
  const offered = QUALITY_CHARTS[view] ?? [];
  return (
    offered.find((option) => option.value === chosen)?.value ??
    offered[0]?.value ??
    "horizontal_bar"
  );
}

/**
 * Worst first, in the order the chosen chart will read them.
 *
 * Which way round that is depends on the chart. A horizontal bar's category
 * axis is drawn upwards from the origin, so the first row lands at the bottom
 * of the plot: sorted the way it reads - biggest number first - the chart came
 * out with the worst check at the foot of the widget, under everything that
 * did not matter. Columns, slices and table rows all run the other way, from
 * the top left, and there the worst check belongs first in the data.
 */
export function worstFirst(
  checks: any[],
  of: (check: any) => number,
  horizontal = true,
): any[] {
  const ordered = [...checks].sort((a, b) => of(b) - of(a));
  return horizontal ? ordered.reverse() : ordered;
}

/**
 * The checks as a chart of their failure rates, worst first.
 *
 * One bar per check, coloured by what it found rather than by where it sits,
 * which is the whole reason to draw this rather than read the list: a board on
 * a wall is read from across the room, and the shape of the red is the message.
 */
export function rateResult(checks: any[], horizontal = true): QueryResult {
  const ordered = worstFirst(
    checks,
    (check) => check.failure_rate ?? 0,
    horizontal,
  );
  return {
    columns: [
      { name: "check", label: "Check", type: "dimension", data_type: "text" },
      {
        name: "rate",
        label: "% of rows failing",
        type: "measure",
        data_type: "number",
      },
    ],
    rows: ordered.map((check) => [
      check.name,
      round2((check.failure_rate ?? 0) * 100),
    ]),
    row_count: ordered.length,
    truncated: false,
    sql: "",
    duration_ms: 0,
  };
}

/** How many rows each check flagged, for the panel drawn as counts. */
export function countResult(checks: any[], horizontal = true): QueryResult {
  const ordered = worstFirst(
    checks,
    (check) => check.failed_rows ?? 0,
    horizontal,
  );
  return {
    columns: [
      { name: "check", label: "Check", type: "dimension", data_type: "text" },
      {
        name: "rows",
        label: "Rows flagged",
        type: "measure",
        data_type: "number",
      },
    ],
    rows: ordered.map((check) => [check.name, check.failed_rows ?? 0]),
    row_count: ordered.length,
    truncated: false,
    sql: "",
    duration_ms: 0,
  };
}

/** The stored runs, one line per check: is this getting better or worse. */
export function trendResult(history: any): QueryResult {
  const series = history?.series ?? [];
  return {
    columns: [
      { name: "day", label: "Day", type: "dimension", data_type: "date" },
      ...series.map((line: any) => ({
        name: line.id,
        label: line.name,
        type: "measure" as const,
        data_type: "number" as const,
      })),
    ],
    rows: (history?.days ?? []).map((day: string, index: number) => [
      shortDay(day),
      ...series.map((line: any) => line.values[index] ?? null),
    ]),
    row_count: (history?.days ?? []).length,
    truncated: false,
    sql: "",
    duration_ms: 0,
  };
}

export const round2 = (value: number) => Math.round(value * 100) / 100;

export const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/**
 * "26 Aug" rather than "2026-08-26".
 *
 * A fortnight of full dates does not fit across a widget, and the year is the
 * same on every one of them. Cut from the string rather than parsed into a
 * Date: an ISO day parsed as a moment is midnight UTC, which in Port Vila is
 * the same day and in Lima is the day before.
 */
export function shortDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  if (!year || !month || !date) return day;
  return `${date} ${MONTHS[month - 1] ?? month}`;
}
