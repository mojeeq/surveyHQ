import { useMutation, useQuery } from "@tanstack/react-query";

import { useEffect, useState } from "react";

import { api, downloadFile } from "@/lib/api";

import { useToast } from "@/hooks/useToast";

import { formatNumber } from "@/lib/format";

import type {
  Aggregation,
  Chart,
  ChartType,
  DateGrain,
  Dimension,
  FilterGroup,
  Measure,
  QueryResult,
  QuerySpec,
} from "@/lib/types";

import ChartCard from "@/components/ChartCard";

import { BOX_MEASURES } from "@/lib/charts";

import type { BuildOptions } from "@/lib/charts";

import FilterBuilder, { emptyFilter } from "@/components/FilterBuilder";

import { VariablePicker } from "@/components/explore/VariablePicker";

import {
  AGGREGATIONS,
  CHART_TYPES,
  VariableList,
} from "@/components/explore/shared";
import {
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Modal,
  Spinner,
} from "@/components/ui";

/**
 * What a box plot asks for in place of a list of measures.
 *
 * One variable, because the five numbers a box is drawn from are five
 * summaries of the same thing - so a list of measures would be a list with
 * only one right answer in it.
 *
 * The note underneath is there because "box plot" does not say which box plot.
 * These whiskers reach the smallest and largest value in the group rather than
 * one and a half times the box, so nothing sits outside them as an outlier and
 * nothing is quietly left out of the picture. Somebody comparing this against
 * a box drawn in another package has to be told that.
 */
export function BoxMeasure({
  numeric,
  variable,
  onVariable,
}: {
  numeric: NonNullable<VariableList>;
  variable: string;
  onVariable: (next: string) => void;
}) {
  return (
    <div className="space-y-2 rounded-card border border-ink-200 p-3">
      <VariablePicker
        label="Variable to summarise"
        variables={numeric}
        value={variable}
        onChange={onVariable}
      />
      <p className="text-xs text-ink-500">
        Box plots are unweighted, so a survey weight does not move the five
        numbers.
      </p>
      <p className="text-xs text-ink-500 dark:text-dark-500">
        One box for each group, drawn from{" "}
        {BOX_MEASURES.map((measure) => measure.label.toLowerCase()).join(", ")}.
        The whiskers reach the smallest and largest value in the group, so
        nothing is left outside them.
      </p>
    </div>
  );
}

export function AggregateBuilder({
  datasetId,
  datasetName,
  groupable,
  numeric,
  allVariables,
  canSave,
  editing,
  onSaved,
}: {
  datasetId: string;
  datasetName: string;
  groupable: NonNullable<VariableList>;
  numeric: NonNullable<VariableList>;
  allVariables: NonNullable<VariableList>;
  canSave: boolean;
  /** The saved chart being edited, if this was opened from one. */
  editing?: Chart;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [dimensions, setDimensions] = useState<Dimension[]>([]);
  const [measures, setMeasures] = useState<Measure[]>([
    { agg: "count", alias: "count" },
  ]);
  const [filters, setFilters] = useState<FilterGroup>(emptyFilter());
  const [chartType, setChartType] = useState<ChartType>("bar");
  /**
   * The variable a box plot summarises, and the weight it is summarised under.
   *
   * Kept apart from the measure list rather than written into it. A box plot is
   * five aggregations of one variable, and putting those five in the list would
   * mean rewriting it every time the chart type changed - and leaving somebody
   * who switched to a bar chart and back with five bars per category. Held here,
   * the two builders do not disturb each other, and the five are written only
   * into the query that is sent.
   */
  const [boxVariable, setBoxVariable] = useState("");
  const [display, setDisplay] = useState<BuildOptions>({ sort: "value_desc" });
  const [limit, setLimit] = useState(50);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [showSql, setShowSql] = useState(false);
  /** Set when a chart's saved query has just been loaded and wants running. */
  const [pending, setPending] = useState(false);

  // Reset the builder whenever the dataset changes; variable names differ.
  useEffect(() => {
    setDimensions([]);
    setMeasures([{ agg: "count", alias: "count" }]);
    setBoxVariable("");
    setFilters(emptyFilter());
    setResult(null);
  }, [datasetId]);

  // A chart opened for editing fills the builder with what it was built from.
  useEffect(() => {
    if (!editing) return;
    const saved = (editing.spec?.query ?? editing.spec) as
      | QuerySpec
      | undefined;
    if (!saved) return;
    const savedDimensions = saved.dimensions ?? [];
    setDimensions(
      editing.chart_type === "kpi"
        ? savedDimensions.filter(
            (dimension) => dimension.alias !== "__kpi_category",
          )
        : savedDimensions,
    );
    setMeasures(saved.measures ?? [{ agg: "count", alias: "count" }]);
    // A saved box plot carries the five; which variable they are five of is
    // read back off any one of them.
    const middle = saved.measures?.find(
      (measure) => measure.alias === "box_median",
    );
    if (middle) {
      setBoxVariable(middle.variable ?? "");
    }
    setFilters(saved.filters ?? emptyFilter());
    setLimit(saved.limit ?? 50);
    setChartType(editing.chart_type as ChartType);
    setDisplay(
      (editing.spec?.options as BuildOptions) ?? { sort: "value_desc" },
    );
    setPending(true);
  }, [editing]);

  // Run once the prefilled query has reached the state the request is built
  // from, rather than from inside the effect that fills it in. An ungrouped
  // KPI is a valid one-row query, so a grouping is not a prerequisite.
  useEffect(() => {
    if (!pending) return;
    setPending(false);
    run.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, dimensions]);

  const isBox = chartType === "boxplot";
  const isKpi = chartType === "kpi";
  /** Falls back to the first numeric variable until one has been picked. */
  const boxColumn = boxVariable || numeric[0]?.name || "";
  const selectedKpi = measures[0];
  type KpiDisplay = BuildOptions & {
    kpiVariable?: string;
    kpiTarget?: string;
  };
  const kpiDisplay = display as KpiDisplay;
  const kpiColumn =
    kpiDisplay.kpiVariable || selectedKpi?.variable || groupable[0]?.name || "";
  const kpiVariable = allVariables.find(
    (variable) => variable.name === kpiColumn,
  );
  const kpiTargets = Object.values(kpiVariable?.value_labels ?? {});
  const defaultKpiTarget =
    kpiVariable?.value_labels?.["1"] ?? kpiTargets[0] ?? "1";
  const kpiTarget = kpiDisplay.kpiTarget ?? defaultKpiTarget;
  // The KPI variable itself is always the final dimension. Any copy of it in
  // Group by is removed so it cannot accidentally turn every card into 100%.
  const kpiGroups = dimensions.filter(
    (dimension) => dimension.variable !== kpiColumn,
  );
  const queryDimensions: Dimension[] = isKpi
    ? [...kpiGroups, { variable: kpiColumn, alias: "__kpi_category" }]
    : dimensions;
  const queryMeasures: Measure[] = isBox
    ? BOX_MEASURES.map((measure) => ({
        agg: measure.agg as Aggregation,
        variable: boxColumn,
        alias: measure.alias,
        weight: null,
      }))
    : isKpi
      ? [
          {
            agg: "share",
            alias: "kpi_share",
            weight: selectedKpi?.weight ?? null,
          },
        ]
      : measures;

  const spec: QuerySpec = {
    dimensions: queryDimensions,
    measures: queryMeasures,
    filters,
    // KPI category shares are re-normalised inside each requested group by the
    // renderer, so query ordering is immaterial and all valid categories must
    // be returned. Dropping missing categories gives the usual valid-percent
    // denominator used in official-statistics tables.
    sort: isBox
      ? [{ field: "box_median", direction: "desc" }]
      : isKpi
        ? []
        : measures.length
          ? [{ field: measures[0].alias || measures[0].agg, direction: "desc" }]
          : [],
    limit: isKpi ? 100000 : limit,
    use_labels: true,
    drop_missing: isKpi,
  };

  const run = useMutation({
    mutationFn: () =>
      api.post<QueryResult>("/analytics/query", {
        dataset_id: datasetId,
        spec,
      }),
    onSuccess: setResult,
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const suggestions = useQuery({
    queryKey: ["suggestions", datasetId],
    queryFn: () => api.post<any[]>(`/analytics/datasets/${datasetId}/suggest`),
  });

  return (
    <div className="mt-4 grid gap-6 lg:grid-cols-[330px_1fr]">
      <div className="space-y-4">
        <Card title="Group by">
          {dimensions.map((dimension, index) => {
            const variable = allVariables.find(
              (v) => v.name === dimension.variable,
            );
            return (
              <div
                key={index}
                className="mb-3 rounded-card border border-ink-200 p-3"
              >
                <div className="flex items-center gap-2">
                  <VariablePicker
                    className="flex-1"
                    label={`Group by, level ${index + 1}`}
                    variables={groupable}
                    value={dimension.variable}
                    onChange={(next) =>
                      setDimensions(
                        dimensions.map((d, i) =>
                          i === index ? { ...d, variable: next, grain: null } : d,
                        ),
                      )
                    }
                  />
                  <button
                    className="btn-ghost btn-sm text-red-600"
                    onClick={() =>
                      setDimensions(dimensions.filter((_, i) => i !== index))
                    }
                  >
                    ✕
                  </button>
                </div>
                {variable?.var_type === "datetime" && (
                  <select
                    className="input mt-2 py-1.5 text-xs"
                    value={dimension.grain ?? "day"}
                    onChange={(event) =>
                      setDimensions(
                        dimensions.map((d, i) =>
                          i === index
                            ? { ...d, grain: event.target.value as DateGrain }
                            : d,
                        ),
                      )
                    }
                  >
                    {["day", "week", "month", "quarter", "year"].map(
                      (grain) => (
                        <option key={grain} value={grain}>
                          By {grain}
                        </option>
                      ),
                    )}
                  </select>
                )}
                {variable?.var_type === "numeric" && (
                  <input
                    className="input mt-2 py-1.5 text-xs"
                    type="number"
                    placeholder="Bin width (optional)"
                    value={dimension.bin_width ?? ""}
                    onChange={(event) =>
                      setDimensions(
                        dimensions.map((d, i) =>
                          i === index
                            ? {
                                ...d,
                                bin_width: event.target.value
                                  ? Number(event.target.value)
                                  : null,
                              }
                            : d,
                        ),
                      )
                    }
                  />
                )}
                {index === 0 && (
                  <input
                    className="input mt-2 py-1.5 text-xs"
                    type="number"
                    placeholder="Keep top N (rest become Other)"
                    value={dimension.limit ?? ""}
                    onChange={(event) =>
                      setDimensions(
                        dimensions.map((d, i) =>
                          i === index
                            ? {
                                ...d,
                                limit: event.target.value
                                  ? Number(event.target.value)
                                  : null,
                              }
                            : d,
                        ),
                      )
                    }
                  />
                )}
              </div>
            );
          })}
          {dimensions.length < 2 && (
            <button
              className="btn-secondary btn-sm w-full"
              onClick={() =>
                setDimensions([
                  ...dimensions,
                  { variable: groupable[0]?.name ?? "" },
                ])
              }
              disabled={!groupable.length}
            >
              + Add grouping
            </button>
          )}
        </Card>

        <Card title={isBox ? "Summarise" : isKpi ? "Percentage" : "Measure"}>
          {isBox ? (
            <BoxMeasure
              numeric={numeric}
              variable={boxColumn}
              onVariable={setBoxVariable}
            />
          ) : isKpi ? (
            <div className="space-y-2 rounded-card border border-ink-200 p-3">
              <Field
                label="Variable"
                hint="The question or categorical variable whose category you want as a percentage."
              >
                <VariablePicker
                  label="KPI variable"
                  variables={groupable}
                  value={kpiColumn}
                  onChange={(chosen) => {
                    const next = allVariables.find(
                      (variable) => variable.name === chosen,
                    );
                    const labels = Object.values(next?.value_labels ?? {});
                    const target =
                      next?.value_labels?.["1"] ?? labels[0] ?? "1";
                    setMeasures([
                      {
                        agg: "share",
                        alias: "kpi_share",
                        weight: selectedKpi?.weight ?? null,
                      },
                    ]);
                    setDisplay({
                      ...display,
                      kpiVariable: chosen,
                      kpiTarget: target,
                    } as BuildOptions);
                  }}
                />
              </Field>
              <Field
                label="Category to display"
                hint="For labelled survey variables choose the answer label. For unlabelled values enter the stored value, e.g. 1, Urban or Employed."
              >
                {kpiTargets.length ? (
                  <select
                    className="input py-1.5 text-xs"
                    value={kpiTarget}
                    onChange={(event) =>
                      setDisplay({
                        ...display,
                        kpiTarget: event.target.value,
                      } as BuildOptions)
                    }
                  >
                    {kpiTargets.map((label, index) => (
                      <option key={`${label}-${index}`} value={label}>
                        {label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="input py-1.5 text-xs"
                    value={kpiTarget}
                    onChange={(event) =>
                      setDisplay({
                        ...display,
                        kpiTarget: event.target.value,
                      } as BuildOptions)
                    }
                    placeholder="1"
                  />
                )}
              </Field>
              <Field label="Survey weight">
                <VariablePicker
                  label="Weight"
                  variables={numeric}
                  value={selectedKpi?.weight ?? ""}
                  onChange={(next) =>
                    setMeasures([
                      {
                        agg: "share",
                        alias: "kpi_share",
                        weight: next || null,
                      },
                    ])
                  }
                  emptyOption="Unweighted"
                />
              </Field>
              <p className="text-xs text-ink-500 dark:text-dark-500">
                The card shows this category as a percentage of valid responses
                to the variable. Add Sex, Province or another grouping above to
                calculate the percentage separately inside each group.
              </p>
            </div>
          ) : (
            <>
              {measures.map((measure, index) => {
                const definition = AGGREGATIONS.find(
                  (a) => a.value === measure.agg,
                );
                return (
                  <div
                    key={index}
                    className="mb-3 space-y-2 rounded-card border border-ink-200 p-3"
                  >
                    <div className="flex items-center gap-2">
                      <select
                        className="input flex-1 py-1.5 text-xs"
                        aria-label="Aggregation"
                        value={measure.agg}
                        onChange={(event) => {
                          const agg = event.target.value as Aggregation;
                          const needs = AGGREGATIONS.find(
                            (a) => a.value === agg,
                          )?.needsVariable;
                          setMeasures(
                            measures.map((m, i) =>
                              i === index
                                ? {
                                    ...m,
                                    agg,
                                    weight: [
                                      "count",
                                      "share",
                                      "sum",
                                      "mean",
                                    ].includes(agg)
                                      ? m.weight
                                      : null,
                                    variable: needs
                                      ? m.variable || numeric[0]?.name
                                      : null,
                                    alias: needs
                                      ? `${agg}_${m.variable || numeric[0]?.name}`
                                      : agg,
                                  }
                                : m,
                            ),
                          );
                        }}
                      >
                        {AGGREGATIONS.map((a) => (
                          <option key={a.value} value={a.value}>
                            {a.label}
                          </option>
                        ))}
                      </select>
                      {measures.length > 1 && (
                        <button
                          className="btn-ghost btn-sm text-red-600"
                          onClick={() =>
                            setMeasures(measures.filter((_, i) => i !== index))
                          }
                        >
                          ✕
                        </button>
                      )}
                    </div>
                    {definition?.needsVariable && (
                      <VariablePicker
                        label={`Measure ${index + 1} variable`}
                        variables={numeric}
                        value={measure.variable ?? ""}
                        onChange={(next) =>
                          setMeasures(
                            measures.map((m, i) =>
                              i === index
                                ? { ...m, variable: next, alias: `${m.agg}_${next}` }
                                : m,
                            ),
                          )
                        }
                      />
                    )}
                    <VariablePicker
                      label={`Measure ${index + 1} survey weight`}
                      variables={numeric}
                      value={measure.weight ?? ""}
                      onChange={(next) =>
                        setMeasures(
                          measures.map((m, i) =>
                            i === index ? { ...m, weight: next || null } : m,
                          ),
                        )
                      }
                      emptyOption="Unweighted"
                      disabled={
                        !["count", "share", "sum", "mean"].includes(measure.agg)
                      }
                    />
                  </div>
                );
              })}
              <button
                className="btn-secondary btn-sm w-full"
                onClick={() =>
                  setMeasures([
                    ...measures,
                    { agg: "count", alias: `count_${measures.length}` },
                  ])
                }
              >
                + Add measure
              </button>
            </>
          )}
        </Card>

        <Card title="Filters">
          <FilterBuilder
            variables={allVariables}
            value={filters}
            onChange={setFilters}
          />
        </Card>

        <Card title="Display">
          <Field
            label="Chart type"
            hint={
              chartType === "population_pyramid"
                ? "Group by an age band and then by sex: the bands become the axis, the two sexes the two sides."
                : isBox
                  ? "Group by the thing to compare across - province, interviewer, month - and each one gets a box."
                  : isKpi
                    ? "Shows one selected category as a weighted percentage. Add a grouping such as sex to calculate it separately within each group."
                    : undefined
            }
          >
            <select
              className="input py-1.5 text-xs"
              value={chartType}
              onChange={(event) => {
                const next = event.target.value as ChartType;
                setChartType(next);
                if (next === "kpi") {
                  const variable =
                    allVariables.find(
                      (item) => item.name === measures[0]?.variable,
                    ) ?? groupable[0];
                  const labels = Object.values(variable?.value_labels ?? {});
                  const target =
                    variable?.value_labels?.["1"] ?? labels[0] ?? "1";
                  setMeasures([
                    {
                      agg: "share",
                      alias: "kpi_share",
                      weight: measures[0]?.weight ?? null,
                    },
                  ]);
                  setDisplay({
                    ...display,
                    decimals: display.decimals ?? 1,
                    kpiVariable: variable?.name ?? "",
                    kpiTarget: target,
                  } as BuildOptions);
                }
              }}
            >
              {CHART_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Order">
            <select
              className="input py-1.5 text-xs"
              value={display.sort ?? "none"}
              onChange={(event) =>
                setDisplay({
                  ...display,
                  sort: event.target.value as BuildOptions["sort"],
                })
              }
            >
              <option value="value_desc">Largest first</option>
              <option value="value_asc">Smallest first</option>
              <option value="label_asc">By name (A-Z)</option>
              <option value="label_desc">By name (Z-A)</option>
              <option value="none">As the query returned them</option>
            </select>
          </Field>

          <Field
            label="Show only the top"
            hint={
              isBox
                ? 'The rest are left off. Boxes cannot be added together, so there is no "Other" box to put them in.'
                : "The rest are added together into one 'Other'. Blank keeps them all."
            }
          >
            <input
              className="input py-1.5 text-xs"
              type="number"
              min={1}
              max={50}
              value={display.topN ?? ""}
              placeholder="all"
              onChange={(event) =>
                setDisplay({
                  ...display,
                  topN: Number(event.target.value) || undefined,
                })
              }
            />
          </Field>

          <Field
            label="Value axis title"
            hint="Blank uses the measure's own name."
          >
            <input
              className="input py-1.5 text-xs"
              value={display.valueTitle ?? ""}
              onChange={(event) =>
                setDisplay({ ...display, valueTitle: event.target.value })
              }
            />
          </Field>

          <div className="grid grid-cols-2 gap-2">
            <Field label="Axis from">
              <input
                className="input py-1.5 text-xs"
                type="number"
                placeholder="auto"
                value={display.valueMin ?? ""}
                onChange={(event) =>
                  setDisplay({
                    ...display,
                    valueMin:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  })
                }
              />
            </Field>
            <Field label="to">
              <input
                className="input py-1.5 text-xs"
                type="number"
                placeholder="auto"
                value={display.valueMax ?? ""}
                onChange={(event) =>
                  setDisplay({
                    ...display,
                    valueMax:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  })
                }
              />
            </Field>
          </div>

          <Field
            label="Target line"
            hint="A dashed rule across the plot, e.g. the target."
          >
            <div className="grid grid-cols-2 gap-2">
              <input
                className="input py-1.5 text-xs"
                type="number"
                placeholder="value"
                value={display.referenceValue ?? ""}
                onChange={(event) =>
                  setDisplay({
                    ...display,
                    referenceValue:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  })
                }
              />
              <input
                className="input py-1.5 text-xs"
                placeholder="label"
                value={display.referenceLabel ?? ""}
                onChange={(event) =>
                  setDisplay({ ...display, referenceLabel: event.target.value })
                }
              />
            </div>
          </Field>

          <div className="mb-3 space-y-1.5 text-xs text-ink-700">
            {/* Offered on every chart type. It used to be withheld from lines,
                areas and scatters because a number on each of a hundred points
                is unreadable - but on a twelve-month series it is exactly what
                a printed report needs, and the count guard below already drops
                the labels when there are too many marks to read. */}
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={Boolean(display.showValues)}
                onChange={(event) =>
                  setDisplay({ ...display, showValues: event.target.checked })
                }
              />
              Print the numbers on the chart
              <span className="text-ink-400">(up to 24 marks)</span>
            </label>
            {(chartType === "stacked_bar" || chartType === "area") && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={Boolean(display.percentStack)}
                  onChange={(event) =>
                    setDisplay({
                      ...display,
                      percentStack: event.target.checked,
                    })
                  }
                />
                Stack to 100% (composition, not size)
              </label>
            )}
            {(chartType === "line" || chartType === "area") && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={Boolean(display.smooth)}
                  onChange={(event) =>
                    setDisplay({ ...display, smooth: event.target.checked })
                  }
                />
                Smooth the line
              </label>
            )}
          </div>

          <Field label="Row limit">
            <input
              className="input py-1.5 text-xs"
              type="number"
              min={1}
              max={10000}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value) || 50)}
            />
          </Field>
          <button
            className="btn-primary w-full"
            onClick={() => run.mutate()}
            disabled={run.isPending}
          >
            {run.isPending && <Spinner className="h-4 w-4 text-white" />}
            Run query
          </button>
        </Card>
      </div>

      <div className="space-y-4">
        {!result && suggestions.data && suggestions.data.length > 0 && (
          <Card
            title="Suggested analyses"
            subtitle="Built from this dataset's own variables"
          >
            <div className="flex flex-wrap gap-2">
              {suggestions.data.map((suggestion, index) => (
                <button
                  key={index}
                  className="btn-secondary btn-sm"
                  onClick={() => {
                    setDimensions(suggestion.spec.dimensions ?? []);
                    setMeasures(suggestion.spec.measures ?? [{ agg: "count" }]);
                    setChartType(suggestion.chart_type);
                    setTimeout(() => run.mutate(), 0);
                  }}
                >
                  {suggestion.title}
                </button>
              ))}
            </div>
          </Card>
        )}

        <Card
          title="Result"
          subtitle={
            result
              ? `${formatNumber(result.row_count)} rows in ${result.duration_ms} ms`
              : "Configure a query and run it"
          }
          actions={
            result && (
              <>
                <button
                  className="btn-ghost btn-sm"
                  onClick={() => setShowSql(!showSql)}
                >
                  {showSql ? "Hide" : "Show"} SQL
                </button>
                <button
                  className="btn-secondary btn-sm"
                  onClick={() =>
                    downloadFile(
                      "/analytics/query/export?format=csv",
                      { dataset_id: datasetId, spec },
                      "results.csv",
                    )
                  }
                >
                  CSV
                </button>
                <button
                  className="btn-secondary btn-sm"
                  onClick={() =>
                    downloadFile(
                      "/analytics/query/export?format=xlsx",
                      { dataset_id: datasetId, spec },
                      "results.xlsx",
                    )
                  }
                >
                  Excel
                </button>
                {canSave && (
                  <button
                    className="btn-primary btn-sm"
                    onClick={() => setSaveOpen(true)}
                  >
                    {editing ? "Save changes" : "Save as chart"}
                  </button>
                )}
              </>
            )
          }
        >
          {run.isPending ? (
            <Loading label="Running query" />
          ) : run.error ? (
            <ErrorNote error={run.error} />
          ) : !result ? (
            <EmptyState
              icon="◱"
              title="Nothing to show yet"
              description="Pick a grouping and a measure, then run the query."
            />
          ) : (
            <>
              {result.truncated && (
                <p className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Showing the first {formatNumber(result.row_count)} rows. Raise
                  the row limit to see more.
                </p>
              )}
              <ChartCard
                result={result}
                chartType={chartType}
                height={420}
                display={display}
              />
              {showSql && (
                <pre className="mt-4 overflow-x-auto rounded-card bg-ink-900 p-3 text-xs text-ink-100">
                  {result.sql}
                </pre>
              )}
            </>
          )}
        </Card>
      </div>

      <SaveChartModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        datasetId={datasetId}
        datasetName={datasetName}
        chartType={chartType}
        display={display}
        spec={spec}
        editing={editing}
        onSaved={onSaved}
      />
    </div>
  );
}

export function SaveChartModal({
  open,
  onClose,
  datasetId,
  datasetName,
  chartType,
  display,
  spec,
  editing,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  datasetId: string;
  datasetName: string;
  chartType: ChartType;
  /** How it is drawn, saved with it so a dashboard shows the same chart. */
  display: BuildOptions;
  spec: QuerySpec;
  /** The chart this was opened from, which is updated rather than duplicated. */
  editing?: Chart;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(editing?.name ?? "");
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name || editing?.name || `Chart on ${datasetName}`,
        dataset_id: datasetId,
        chart_type: chartType,
        spec: { query: spec, options: display },
      };
      return editing
        ? api.patch(`/dashboards/charts/${editing.id}`, body)
        : api.post("/dashboards/charts", body);
    },
    onSuccess: () => {
      onSaved();
      if (!editing) setName("");
      onClose();
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? `Save changes to "${editing.name}"` : "Save as chart"}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            {editing ? "Save changes" : "Save chart"}
          </button>
        </>
      }
    >
      <Field
        label="Chart name"
        hint="Saved charts can be added to any dashboard."
      >
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={`Chart on ${datasetName}`}
        />
      </Field>
    </Modal>
  );
}
