import { useMutation } from "@tanstack/react-query";

import { useEffect, useState } from "react";

import { api, downloadFile } from "@/lib/api";

import { useToast } from "@/hooks/useToast";

import type {
  Aggregation,
  Chart,
  CrosstabRequest,
  CrosstabResult,
  FilterGroup,
  Measure,
} from "@/lib/types";

import ChartCard from "@/components/ChartCard";

import CrosstabTable from "@/components/CrosstabTable";

import FilterBuilder, { emptyFilter } from "@/components/FilterBuilder";

import { VariablePicker } from "@/components/explore/VariablePicker";

import {
  AGGREGATIONS,
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
 * The Cell values choice that means "no cell values at all".
 *
 * A sentinel rather than an aggregation, because there is no such aggregation:
 * the request carries a null measure and the server answers with the
 * categories and nothing beside them. Prefixed so it can never collide with an
 * aggregation name.
 */
const NO_VALUES = "__no_values";

/**
 * The aggregations a survey weight can be applied to.
 *
 * The server refuses the rest: a weighted median or percentile is a different
 * calculation rather than the same one with a multiplier in it, and pretending
 * otherwise would quietly return the unweighted answer under a weighted name.
 * Mirrors the check in `Measure` so the control is never offered where the
 * request would be rejected.
 */
const WEIGHTABLE = new Set<Aggregation>(["count", "sum", "mean"]);

export function CrosstabBuilder({
  datasetId,
  datasetName,
  groupable,
  numeric,
  allVariables,
  canSave,
  editing,
}: {
  datasetId: string;
  datasetName: string;
  groupable: NonNullable<VariableList>;
  numeric: NonNullable<VariableList>;
  allVariables: NonNullable<VariableList>;
  canSave: boolean;
  /** The saved cross-tabulation being edited, if this was opened from one. */
  editing?: Chart;
}) {
  const toast = useToast();
  const [rowVariable, setRowVariable] = useState(groupable[0]?.name ?? "");
  const [columnVariable, setColumnVariable] = useState(
    groupable[1]?.name ?? "",
  );
  const [percentages, setPercentages] = useState<
    "none" | "row" | "column" | "total"
  >("none");
  const [measure, setMeasure] = useState<Measure | null>({ agg: "count" });
  // The variables after the first, each a column of its own with the same
  // calculation: the sum of rejections by the supervisor, then by HQ.
  const [moreVariables, setMoreVariables] = useState<string[]>([]);
  // Headings somebody renamed, by the heading the table would otherwise show.
  const [columnHeadings, setColumnHeadings] = useState<Record<string, string>>({});
  const [rowHeading, setRowHeading] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [filters, setFilters] = useState<FilterGroup>(emptyFilter());
  const [result, setResult] = useState<CrosstabResult | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);

  useEffect(() => {
    setRowVariable(groupable[0]?.name ?? "");
    setColumnVariable(groupable[1]?.name ?? "");
    setResult(null);
  }, [datasetId, groupable]);

  // A saved cross-tabulation opened for editing keeps the request it was made
  // from, so this is filling the form back in from it.
  useEffect(() => {
    const saved = editing?.spec?.crosstab as CrosstabRequest | undefined;
    if (!saved) return;
    setRowVariable(saved.row_variable);
    setColumnVariable(saved.column_variable);
    setPercentages(saved.percentages ?? "none");
    // `??` would be wrong here: a saved table with no cell values carries a
    // null measure, and a null that means "none" must not be read as "unset".
    setMeasure(saved.measure === undefined ? { agg: "count" } : saved.measure);
    if (saved.measures && saved.measures.length > 1) {
      setMeasure(saved.measures[0]);
      setMoreVariables(saved.measures.slice(1).map((one) => one.variable ?? ""));
    } else {
      setMoreVariables([]);
    }
    setColumnHeadings(saved.column_headings ?? {});
    setRowHeading(saved.row_heading ?? "");
    setFilters(saved.filters ?? emptyFilter());
  }, [editing]);

  const needsVariable = Boolean(
    measure && AGGREGATIONS.find((a) => a.value === measure.agg)?.needsVariable,
  );
  const extra = needsVariable && !columnVariable ? moreVariables : [];
  const many = extra.length > 0;
  // Counts and sums add along a row, so a total and its percentages mean
  // something; a row of means does not.
  const adds = !many || measure?.agg === "sum" || measure?.agg === "count";

  const body: CrosstabRequest = {
    row_variable: rowVariable,
    column_variable: columnVariable,
    measure,
    measures:
      many && measure
        ? [measure, ...extra.map((variable) => ({ ...measure, variable }))]
        : [],
    column_headings: columnHeadings,
    row_heading: rowHeading,
    filters,
    percentages: adds ? percentages : "none",
    include_totals: true,
    use_labels: true,
  };

  const run = useMutation({
    mutationFn: () =>
      api.post<CrosstabResult>(
        `/analytics/datasets/${datasetId}/crosstab`,
        body,
      ),
    onSuccess: setResult,
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  return (
    <div className="mt-4 grid gap-6 lg:grid-cols-[330px_1fr]">
      <div className="space-y-4">
        <Card title="Table setup">
          <Field
            label="Rows"
            hint="Leave one of the two empty to tabulate a single variable on its own."
          >
            <VariablePicker
              label="Rows"
              variables={groupable}
              value={rowVariable}
              onChange={setRowVariable}
              emptyOption="No rows"
            />
          </Field>
          <Field
            label="Columns"
            hint={
              many
                ? "The variables are the columns. Remove the extra variables to cross with a column variable instead."
                : undefined
            }
          >
            <VariablePicker
              label="Columns"
              variables={groupable}
              value={columnVariable}
              disabled={many}
              title={many ? "The variables below are the columns" : undefined}
              onChange={(next) => {
                setColumnVariable(next);
                // Two variables crossed with nothing in the cells is a grid of
                // blanks, so choosing a column brings the count back rather
                // than leaving a request the server will refuse.
                if (next && !measure) setMeasure({ agg: "count" });
              }}
              emptyOption="No columns"
            />
          </Field>
          <Field label="Cell values">
            <select
              className="input py-1.5 text-xs"
              value={measure ? measure.agg : NO_VALUES}
              onChange={(event) => {
                if (event.target.value === NO_VALUES) {
                  setMeasure(null);
                  setPercentages("none");
                  return;
                }
                const agg = event.target.value as Aggregation;
                const needs = AGGREGATIONS.find(
                  (a) => a.value === agg,
                )?.needsVariable;
                setMeasure({
                  agg,
                  variable: needs ? numeric[0]?.name : null,
                  // Dropped rather than carried along invisibly: the server
                  // rejects a weight on a median, and a control that has
                  // scrolled out of view must not decide the request.
                  weight: WEIGHTABLE.has(agg) ? (measure?.weight ?? null) : null,
                });
              }}
            >
              {/* Only offered without a column variable: two variables crossed
                  with nothing in the cells is a grid of blanks, and nothing
                  can be read off it. */}
              {!columnVariable && (
                <option value={NO_VALUES}>None (just list the categories)</option>
              )}
              {AGGREGATIONS.filter((a) => a.value !== "share").map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </Field>
          {measure && needsVariable && (
            <Field
              label={many ? "Of variables (a column each)" : "Of variable"}
              hint={
                columnVariable
                  ? undefined
                  : "Add more to show several side by side, one column each."
              }
            >
              <div className="space-y-2">
                <VariablePicker
                  label="Of variable"
                  variables={numeric}
                  value={measure.variable ?? ""}
                  onChange={(next) => setMeasure({ ...measure, variable: next })}
                />
                {extra.map((variable, index) => (
                  <div key={index} className="flex items-center gap-1.5">
                    <VariablePicker
                      label={`Variable ${index + 2}`}
                      variables={numeric}
                      value={variable}
                      className="min-w-0 flex-1"
                      onChange={(next) =>
                        setMoreVariables(
                          moreVariables.map((one, i) => (i === index ? next : one)),
                        )
                      }
                    />
                    <button
                      type="button"
                      className="btn-ghost btn-sm text-red-600"
                      aria-label={`Remove variable ${index + 2}`}
                      onClick={() =>
                        setMoreVariables(moreVariables.filter((_, i) => i !== index))
                      }
                    >
                      ✕
                    </button>
                  </div>
                ))}
                {!columnVariable && rowVariable && (
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={() => {
                      // The next one not already in the table, to save a pick.
                      const used = new Set([measure.variable, ...moreVariables]);
                      const next = numeric.find((one) => !used.has(one.name))?.name ?? "";
                      setMoreVariables([...moreVariables, next]);
                    }}
                  >
                    + Another variable
                  </button>
                )}
              </div>
            </Field>
          )}
          {measure && WEIGHTABLE.has(measure.agg) && (
            <Field
              label="Survey weight"
              hint={
                measure.weight
                  ? "Cells estimate the population. Disclosure is still judged on the number of records behind each one."
                  : "Cells count interviews, not the population they stand for."
              }
            >
              <VariablePicker
                label="Survey weight"
                variables={numeric}
                value={measure.weight ?? ""}
                onChange={(next) => setMeasure({ ...measure, weight: next || null })}
                emptyOption="Unweighted"
              />
            </Field>
          )}
          <Field
            label="Percentages"
            hint={
              !measure
                ? "A table with no cell values has nothing to take a percentage of."
                : !adds
                  ? "Only sums and counts add up along a row, so only they have percentages."
                  : undefined
            }
          >
            <select
              className="input py-1.5 text-xs"
              value={adds ? percentages : "none"}
              disabled={!measure || !adds}
              onChange={(event) =>
                setPercentages(event.target.value as typeof percentages)
              }
            >
              {/* "Counts only" was already a half-truth on a table of means.
                  With no cell values at all it is simply wrong, and this is
                  the option that turns percentages off either way. */}
              <option value="none">None</option>
              <option value="row">Row percentages</option>
              <option value="column">Column percentages</option>
              <option value="total">Percent of total</option>
            </select>
          </Field>
        </Card>

        <Card title="Filters">
          <FilterBuilder
            variables={allVariables}
            value={filters}
            onChange={setFilters}
          />
        </Card>

        {/* Pinned while the column scrolls, as on Tabulate & chart. */}
        <div className="sticky bottom-0 z-10 -mx-2 bg-ink-50/90 px-2 py-3 backdrop-blur dark:bg-dark-100/90">
          <button
            className="btn-primary w-full"
            onClick={() => run.mutate()}
            disabled={run.isPending || (!rowVariable && !columnVariable)}
          >
            {run.isPending && <Spinner className="h-4 w-4 text-white" />}
            Build table
          </button>
        </div>
      </div>

      <Card
        title={`Cross-tabulation: ${datasetName}`}
        actions={
          result && (
            <>
              <button
                className="btn-secondary btn-sm"
                onClick={() => setRenaming(true)}
                title="Give the columns the names a reader should see"
              >
                Rename columns
              </button>
              <button
                className="btn-secondary btn-sm"
                onClick={() =>
                  downloadFile(
                    `/analytics/datasets/${datasetId}/crosstab/export`,
                    body,
                    "crosstab.csv",
                  )
                }
              >
                Export CSV
              </button>
              {canSave && (
                <button
                  className="btn-primary btn-sm"
                  onClick={() => setSaveOpen(true)}
                >
                  {editing ? "Save changes" : "Save for dashboards"}
                </button>
              )}
            </>
          )
        }
      >
        {run.isPending ? (
          <Loading />
        ) : run.error ? (
          <ErrorNote error={run.error} />
        ) : !result ? (
          <EmptyState
            icon="▦"
            title="No table yet"
            description="Choose a row and a column variable, then build the table."
          />
        ) : (
          <>
            <CrosstabTable result={result} />

            {/* A table with no cell values has nothing to plot: every bar
                would be zero high. The list of categories is the whole
                answer, so the chart goes rather than sitting there empty. */}
            {result.column_labels.length > 0 && (
              <div className="mt-5">
                <ChartCard
                  showToggle={false}
                  chartType={many && !adds ? "bar" : "stacked_bar"}
                  height={340}
                  result={{
                    columns: [
                      {
                        name: "row",
                        label: result.row_variable,
                        type: "dimension",
                        data_type: "text",
                      },
                      {
                        name: "col",
                        label: result.column_variable,
                        type: "dimension",
                        data_type: "text",
                      },
                      {
                        name: "value",
                        label: "Value",
                        type: "measure",
                        data_type: "number",
                      },
                    ],
                    rows: result.row_labels.flatMap((rowLabel, rowIndex) =>
                      result.column_labels.map((columnLabel, columnIndex) => [
                        rowLabel,
                        result.column_headings?.[columnIndex] || columnLabel,
                        result.values[rowIndex][columnIndex],
                      ]),
                    ),
                    row_count:
                      result.row_labels.length * result.column_labels.length,
                    truncated: false,
                    sql: "",
                    duration_ms: 0,
                  }}
                />
              </div>
            )}
          </>
        )}
      </Card>

      {renaming && result && (
        <RenameColumnsModal
          result={result}
          headings={columnHeadings}
          rowHeading={rowHeading}
          onClose={() => setRenaming(false)}
          onApply={(headings, corner) => {
            setColumnHeadings(headings);
            setRowHeading(corner);
            // Shown at once, without asking the server again: only the
            // headings changed, and the request now carries them for the
            // save and the export.
            setResult({
              ...result,
              column_headings: result.column_labels.map((label) => headings[label] || label),
              row_heading: corner,
            });
            setRenaming(false);
          }}
        />
      )}

      <SaveCrosstabModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        datasetId={datasetId}
        datasetName={datasetName}
        request={body}
        editing={editing}
      />
    </div>
  );
}

/**
 * Naming a table's columns for its reader.
 *
 * Only the headings change. The column a heading sits over is still the
 * category or the value it was, so a renamed heading on a dashboard still
 * filters the page by what it stands for when clicked. Left blank, a column
 * keeps the name the data gives it.
 */
function RenameColumnsModal({
  result,
  headings,
  rowHeading,
  onClose,
  onApply,
}: {
  result: CrosstabResult;
  headings: Record<string, string>;
  rowHeading: string;
  onClose: () => void;
  onApply: (headings: Record<string, string>, rowHeading: string) => void;
}) {
  const [names, setNames] = useState<Record<string, string>>(() =>
    Object.fromEntries(result.column_labels.map((label) => [label, headings[label] ?? ""])),
  );
  const [corner, setCorner] = useState(rowHeading);
  const original = result.row_variable_label || result.row_variable;

  return (
    <Modal
      open
      onClose={onClose}
      title="Rename columns"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() =>
              onApply(
                // Only the columns this table has, and only the ones renamed:
                // a heading for a column that has gone is clutter.
                Object.fromEntries(
                  Object.entries(names)
                    .map(([label, name]) => [label, name.trim()] as const)
                    .filter(([label, name]) => name && name !== label),
                ),
                corner.trim(),
              )
            }
          >
            Rename
          </button>
        </>
      }
    >
      <p className="mb-4 text-sm text-ink-500">
        Only the headings change. Leave one blank to keep the name the data gives it.
      </p>
      {result.row_variable && (
        <Field label="Heading of the rows">
          <input
            className="input"
            aria-label={`New heading for ${original}`}
            placeholder={original}
            value={corner}
            onChange={(event) => setCorner(event.target.value)}
          />
        </Field>
      )}
      <div className="space-y-2">
        {result.column_labels.map((label) => (
          <label key={label} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] items-center gap-3 text-sm">
            <span className="truncate font-mono text-xs text-ink-600" title={label}>
              {label}
            </span>
            <input
              className="input"
              aria-label={`New heading for ${label}`}
              placeholder={label}
              value={names[label] ?? ""}
              onChange={(event) => setNames({ ...names, [label]: event.target.value })}
            />
          </label>
        ))}
      </div>
    </Modal>
  );
}

export function SaveCrosstabModal({
  open,
  onClose,
  datasetId,
  datasetName,
  request,
  editing,
}: {
  open: boolean;
  onClose: () => void;
  datasetId: string;
  datasetName: string;
  request: CrosstabRequest;
  /** The saved cross-tabulation being edited, updated rather than duplicated. */
  editing?: Chart;
}) {
  const toast = useToast();
  const [name, setName] = useState(editing?.name ?? "");

  // A one-way table is "region", not "region by " with nothing after it.
  const defaultName =
    request.measures && request.measures.length > 1
      ? `${request.measures.map((one) => one.variable).join(", ")} by ${request.row_variable}`
      : request.row_variable && request.column_variable
        ? `${request.row_variable} by ${request.column_variable}`
        : request.row_variable || request.column_variable;

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name || editing?.name || defaultName,
        dataset_id: datasetId,
        chart_type: "crosstab",
        // A crosstab spec holds the request rather than a query, and the server
        // branches on that when rendering.
        spec: { crosstab: request },
      };
      return editing
        ? api.patch(`/dashboards/charts/${editing.id}`, body)
        : api.post("/dashboards/charts", body);
    },
    onSuccess: () => {
      toast.push(
        editing
          ? "Cross-tabulation updated"
          : "Cross-tabulation saved; add it to a dashboard",
        "success",
      );
      if (!editing) setName("");
      onClose();
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Save cross-tabulation"
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
            Save
          </button>
        </>
      }
    >
      <Field
        label="Name"
        hint={`Saved against ${datasetName}. It appears alongside charts when adding a dashboard widget.`}
      >
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={defaultName}
          data-suggest=""
        />
      </Field>
    </Modal>
  );
}
