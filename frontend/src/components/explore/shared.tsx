import { formatNumber } from "@/lib/format";

import type {
  Aggregation,
  Chart,
  ChartType,
  Dataset,
  Variable,
} from "@/lib/types";

export const AGGREGATIONS: {
  value: Aggregation;
  label: string;
  needsVariable: boolean;
}[] = [
  { value: "count", label: "Count", needsVariable: false },
  { value: "share", label: "Share of total (%)", needsVariable: false },
  { value: "sum", label: "Sum", needsVariable: true },
  { value: "mean", label: "Mean", needsVariable: true },
  { value: "median", label: "Median", needsVariable: true },
  { value: "min", label: "Minimum", needsVariable: true },
  { value: "max", label: "Maximum", needsVariable: true },
  { value: "stddev", label: "Std deviation", needsVariable: true },
  { value: "p25", label: "25th percentile", needsVariable: true },
  { value: "p75", label: "75th percentile", needsVariable: true },
  { value: "count_distinct", label: "Distinct count", needsVariable: true },
];

export const CHART_TYPES: { value: ChartType; label: string }[] = [
  { value: "kpi", label: "KPI percentage" },
  { value: "bar", label: "Bar" },
  { value: "horizontal_bar", label: "Horizontal bar" },
  { value: "stacked_bar", label: "Stacked bar" },
  { value: "horizontal_stacked_bar", label: "Horizontal stacked bar" },
  { value: "population_pyramid", label: "Population pyramid" },
  { value: "line", label: "Line" },
  { value: "area", label: "Area" },
  { value: "donut", label: "Donut" },
  { value: "pie", label: "Pie" },
  { value: "scatter", label: "Scatter" },
  { value: "boxplot", label: "Box plot" },
  { value: "heatmap", label: "Heatmap" },
  { value: "table", label: "Table" },
];

/** How a variable reads in a picker.
 *
 *  A variable with a value per row will tabulate to as many rows as the limit
 *  allows, which is fine when it is what you asked for and a surprise when it
 *  is not. Saying how many distinct values it holds is the difference.
 */
export function optionLabel(v: Variable): string {
  const named = v.label ? `${v.name} - ${v.label}` : v.name;
  return v.n_unique > 200
    ? `${named} (${formatNumber(v.n_unique)} values)`
    : named;
}

export type Mode = "aggregate" | "crosstab" | "multiselect";

/** Which builder a saved chart was made in, so editing reopens it there.
 *
 *  A cross-tabulation says so in its chart type; a multiple-select does not,
 *  because it is drawn as an ordinary bar. What marks it is the spec: it holds
 *  the columns the question was spread across instead of a query.
 */
export function modeOf(chart: Chart): Mode {
  if (chart.chart_type === "crosstab") return "crosstab";
  if (chart.spec?.multiselect) return "multiselect";
  return "aggregate";
}

/** The chart being edited, but only for the builder that made it. */
export function openedIn(mode: Mode, chart?: Chart): Chart | undefined {
  return chart && modeOf(chart) === mode ? chart : undefined;
}

export type VariableList = Dataset["variables"];
