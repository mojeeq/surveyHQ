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

import {
  AGGREGATIONS,
  VariableList,
  optionLabel,
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
  const [measure, setMeasure] = useState<Measure>({ agg: "count" });
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
    setMeasure(saved.measure ?? { agg: "count" });
    setFilters(saved.filters ?? emptyFilter());
  }, [editing]);

  const body: CrosstabRequest = {
    row_variable: rowVariable,
    column_variable: columnVariable,
    measure,
    filters,
    percentages,
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
            <select
              className="input py-1.5 text-xs"
              value={rowVariable}
              onChange={(event) => setRowVariable(event.target.value)}
            >
              <option value="">No rows</option>
              {groupable.map((v) => (
                <option key={v.name} value={v.name}>
                  {optionLabel(v)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Columns">
            <select
              className="input py-1.5 text-xs"
              value={columnVariable}
              onChange={(event) => setColumnVariable(event.target.value)}
            >
              <option value="">No columns</option>
              {groupable.map((v) => (
                <option key={v.name} value={v.name}>
                  {optionLabel(v)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Cell values">
            <select
              className="input py-1.5 text-xs"
              value={measure.agg}
              onChange={(event) => {
                const agg = event.target.value as Aggregation;
                const needs = AGGREGATIONS.find(
                  (a) => a.value === agg,
                )?.needsVariable;
                setMeasure({ agg, variable: needs ? numeric[0]?.name : null });
              }}
            >
              {AGGREGATIONS.filter((a) => a.value !== "share").map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </Field>
          {AGGREGATIONS.find((a) => a.value === measure.agg)?.needsVariable && (
            <Field label="Of variable">
              <select
                className="input py-1.5 text-xs"
                value={measure.variable ?? ""}
                onChange={(event) =>
                  setMeasure({ ...measure, variable: event.target.value })
                }
              >
                {numeric.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Percentages">
            <select
              className="input py-1.5 text-xs"
              value={percentages}
              onChange={(event) =>
                setPercentages(event.target.value as typeof percentages)
              }
            >
              <option value="none">Counts only</option>
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

        <button
          className="btn-primary w-full"
          onClick={() => run.mutate()}
          disabled={run.isPending || (!rowVariable && !columnVariable)}
        >
          {run.isPending && <Spinner className="h-4 w-4 text-white" />}
          Build table
        </button>
      </div>

      <Card
        title={`Cross-tabulation: ${datasetName}`}
        actions={
          result && (
            <>
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

            <div className="mt-5">
              <ChartCard
                showToggle={false}
                chartType="stacked_bar"
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
                      columnLabel,
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
          </>
        )}
      </Card>

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
    request.row_variable && request.column_variable
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
        />
      </Field>
    </Modal>
  );
}
