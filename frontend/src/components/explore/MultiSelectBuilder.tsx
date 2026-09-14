import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";

import { useToast } from "@/hooks/useToast";

import { formatNumber } from "@/lib/format";

import type {
  Chart,
  ChartType,
  FilterGroup,
  MultiSelectGroup,
  MultiSelectRequest,
  QueryResult,
} from "@/lib/types";

import ChartCard from "@/components/ChartCard";

import type { BuildOptions } from "@/lib/charts";

import FilterBuilder, { emptyFilter } from "@/components/FilterBuilder";

import { VariableList } from "@/components/explore/shared";
import {
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Modal,
  Spinner,
} from "@/components/ui";

export const MULTISELECT_CHARTS: { value: ChartType; label: string }[] = [
  { value: "horizontal_bar", label: "Horizontal bar" },
  { value: "bar", label: "Vertical bar" },
  { value: "donut", label: "Donut" },
  { value: "pie", label: "Pie" },
  { value: "table", label: "Table" },
];

/**
 * A "tick all that apply" question, charted from the columns it arrived as.
 *
 * The question is not in the file: toilet__1, toilet__2 and toilet__3 are, each
 * holding 1 where that option was ticked. Tabulating any one of them answers
 * "how many chose flush", never "what do people use". This puts the set back
 * together - one bar per option, counted down its own column - and the shares
 * add to more than 100, because more than one may be ticked.
 */
export function MultiSelectBuilder({
  datasetId,
  datasetName,
  allVariables,
  canSave,
  editing,
}: {
  datasetId: string;
  datasetName: string;
  allVariables: NonNullable<VariableList>;
  canSave: boolean;
  /** The saved chart being edited, if this was opened from one. */
  editing?: Chart;
}) {
  const toast = useToast();
  const [columns, setColumns] = useState<string[]>([]);
  const [percentOf, setPercentOf] =
    useState<MultiSelectRequest["percent_of"]>("respondents");
  const [sort, setSort] = useState<MultiSelectRequest["sort"]>("value_desc");
  const [show, setShow] = useState<MultiSelectRequest["show"]>("count");
  const [chartType, setChartType] = useState<ChartType>("horizontal_bar");
  const [display, setDisplay] = useState<BuildOptions>({ sort: "none" });
  const [filters, setFilters] = useState<FilterGroup>(emptyFilter());
  const [result, setResult] = useState<QueryResult | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [search, setSearch] = useState("");
  /** Open while the options are being named. */
  const [naming, setNaming] = useState(false);
  /** Set when a saved chart has just been loaded and wants running. */
  const [pending, setPending] = useState(false);

  // Which sets of columns in this file look like one question. Offered rather
  // than guessed at: picking the question by name beats ticking twelve columns.
  const groups = useQuery({
    queryKey: ["multiselect-groups", datasetId],
    queryFn: () =>
      api.get<MultiSelectGroup[]>(
        `/analytics/datasets/${datasetId}/multiselect-groups`,
      ),
    enabled: Boolean(datasetId),
  });

  useEffect(() => {
    setColumns([]);
    setResult(null);
  }, [datasetId]);

  useEffect(() => {
    const saved = editing?.spec?.multiselect;
    if (!saved) return;
    setColumns(saved.columns ?? []);
    setPercentOf(saved.percent_of ?? "respondents");
    setSort(saved.sort ?? "value_desc");
    setShow(saved.show ?? "count");
    setFilters(saved.filters ?? emptyFilter());
    setChartType(editing?.chart_type as ChartType);
    setDisplay((editing?.spec?.options as BuildOptions) ?? { sort: "none" });
    setPending(true);
  }, [editing]);

  const body: MultiSelectRequest = {
    columns,
    filters,
    percent_of: percentOf,
    sort,
    show,
  };

  const run = useMutation({
    mutationFn: () =>
      api.post<QueryResult>(
        `/analytics/datasets/${datasetId}/multiselect`,
        body,
      ),
    onSuccess: setResult,
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  // Run once the loaded columns have reached the state the request is built
  // from, rather than from inside the effect that fills them in.
  useEffect(() => {
    if (!pending || !columns.length) return;
    setPending(false);
    run.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, columns]);

  // Which question the ticked columns belong to, so its options can be shown
  // as a list to include or leave out.
  const group = useMemo(
    () =>
      groups.data?.find((entry) =>
        entry.columns.some((name) => columns.includes(name)),
      ),
    [groups.data, columns],
  );

  const others = useMemo(() => {
    const inGroup = new Set(group?.columns ?? []);
    const needle = search.trim().toLowerCase();
    return allVariables.filter(
      (variable) =>
        !inGroup.has(variable.name) &&
        (needle
          ? `${variable.name} ${variable.label ?? ""}`
              .toLowerCase()
              .includes(needle)
          : columns.includes(variable.name)),
    );
  }, [allVariables, group, columns, search]);

  const toggle = (name: string) =>
    setColumns(
      columns.includes(name)
        ? columns.filter((entry) => entry !== name)
        : [...columns, name],
    );

  return (
    <div className="mt-4 grid gap-6 lg:grid-cols-[330px_1fr]">
      <div className="space-y-4">
        <Card title="The question">
          {groups.isLoading ? (
            <Loading />
          ) : (
            <>
              <Field
                label="Multiple-select question"
                hint={
                  groups.data?.length
                    ? "Found from the column names: toilet__1, toilet__2 and so on are one question."
                    : "No sets of option columns were found in this dataset. Tick the 0/1 columns yourself below."
                }
              >
                <select
                  className="input py-1.5 text-xs"
                  value={group?.stem ?? ""}
                  onChange={(event) => {
                    const chosen = groups.data?.find(
                      (entry) => entry.stem === event.target.value,
                    );
                    setColumns(chosen ? chosen.columns : []);
                    setResult(null);
                  }}
                >
                  <option value="">Choose the columns myself</option>
                  {groups.data?.map((entry) => (
                    <option key={entry.stem} value={entry.stem}>
                      {entry.label === entry.stem
                        ? `${entry.stem} (${entry.columns.length} options)`
                        : `${entry.label} - ${entry.stem} (${entry.columns.length} options)`}
                    </option>
                  ))}
                </select>
              </Field>

              {group && (
                <div className="mb-3">
                  <p className="mb-1.5 text-xs font-medium text-ink-700">
                    Options to show
                    <button
                      className="btn-ghost btn-sm ml-2"
                      onClick={() =>
                        setColumns(
                          columns.length === group.columns.length
                            ? []
                            : [...group.columns],
                        )
                      }
                    >
                      {columns.length === group.columns.length
                        ? "Clear all"
                        : "Tick all"}
                    </button>
                  </p>
                  <div className="max-h-56 space-y-1 overflow-y-auto rounded-card border border-ink-200 p-2">
                    {(
                      group.options ??
                      group.columns.map((column) => ({ column, label: column }))
                    ).map((option) => (
                      <label
                        key={option.column}
                        className="flex items-start gap-2 text-xs text-ink-700"
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={columns.includes(option.column)}
                          onChange={() => toggle(option.column)}
                        />
                        <span>
                          {/* The name the bar will carry, which is what
                                somebody ticking eight boxes out of nineteen is
                                choosing between. The column name follows it,
                                and only where it says something the label does
                                not - printed twice it read as a bug. */}
                          {option.label}
                          {option.label !== option.column && (
                            <span className="ml-1 text-ink-400">
                              {option.column}
                            </span>
                          )}
                        </span>
                      </label>
                    ))}
                  </div>
                  {/* Why the bars are numbered, and what to do about it. The
                      option text is usually in the file and is read from it;
                      an export that carries none leaves nothing to read, and
                      the answer is to write the names once, here, where the
                      question is in front of you. */}
                  {group.unnamed && (
                    <p className="mt-1.5 text-xs text-amber-700">
                      This file gives no names for these options, so they are
                      numbered.
                      {canSave ? (
                        <>
                          {" "}
                          <button
                            className="font-medium underline"
                            onClick={() => setNaming(true)}
                          >
                            Name them
                          </button>{" "}
                          and the names stay with the dataset - every chart,
                          filter and table shows them.
                        </>
                      ) : (
                        " Ask somebody who can edit this dataset to name them."
                      )}
                    </p>
                  )}
                  {!group.unnamed && canSave && (
                    <button
                      className="btn-ghost btn-sm mt-1 px-0 text-xs"
                      onClick={() => setNaming(true)}
                    >
                      Rename the options
                    </button>
                  )}
                </div>
              )}

              {!group && (
                <div className="mb-3">
                  <input
                    className="input mb-2 py-1.5 text-xs"
                    placeholder="Search the columns"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                  <div className="max-h-56 space-y-1 overflow-y-auto rounded-card border border-ink-200 p-2">
                    {others.length === 0 && (
                      <p className="p-1 text-xs text-ink-500">
                        Search for the columns that hold this question, then
                        tick them.
                      </p>
                    )}
                    {others.map((variable) => (
                      <label
                        key={variable.name}
                        className="flex items-start gap-2 text-xs text-ink-700"
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={columns.includes(variable.name)}
                          onChange={() => toggle(variable.name)}
                        />
                        <span>
                          {variable.label || variable.name}
                          {variable.label && (
                            <span className="ml-1 text-ink-400">
                              {variable.name}
                            </span>
                          )}
                        </span>
                      </label>
                    ))}
                  </div>
                  <p className="mt-1 text-xs text-ink-500">
                    {columns.length} column{columns.length === 1 ? "" : "s"}{" "}
                    ticked
                  </p>
                </div>
              )}
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
          <Field label="Chart type">
            <select
              className="input py-1.5 text-xs"
              value={chartType}
              onChange={(event) => {
                const next = event.target.value as ChartType;
                setChartType(next);
                // A table is the one place both numbers belong together; on a
                // chart they are two scales sharing one axis.
                if (next === "table" && show !== "both") setShow("both");
                if (next !== "table" && show === "both") setShow("count");
              }}
            >
              {MULTISELECT_CHARTS.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Show">
            <select
              className="input py-1.5 text-xs"
              value={show}
              onChange={(event) =>
                setShow(event.target.value as MultiSelectRequest["show"])
              }
            >
              <option value="count">How many chose it</option>
              <option value="percent">Percent</option>
              <option value="both">Both (best in a table)</option>
            </select>
          </Field>
          <Field
            label="Percent of"
            hint="Respondents is the usual reading: the shares add to more than 100 because more than one option may be ticked."
          >
            <select
              className="input py-1.5 text-xs"
              value={percentOf}
              onChange={(event) =>
                setPercentOf(
                  event.target.value as MultiSelectRequest["percent_of"],
                )
              }
            >
              <option value="respondents">
                People who were asked the question
              </option>
              <option value="rows">Every row in the dataset</option>
            </select>
          </Field>
          <Field label="Order">
            <select
              className="input py-1.5 text-xs"
              value={sort}
              onChange={(event) =>
                setSort(event.target.value as MultiSelectRequest["sort"])
              }
            >
              <option value="value_desc">Most chosen first</option>
              <option value="value_asc">Least chosen first</option>
              <option value="label_asc">By option name (A-Z)</option>
              <option value="none">In the order the columns come</option>
            </select>
          </Field>
          <label className="mb-3 flex items-center gap-2 text-xs text-ink-700">
            <input
              type="checkbox"
              checked={Boolean(display.showValues)}
              onChange={(event) =>
                setDisplay({ ...display, showValues: event.target.checked })
              }
            />
            Print the numbers on the chart
          </label>
          <button
            className="btn-primary w-full"
            onClick={() => run.mutate()}
            disabled={run.isPending || !columns.length}
          >
            {run.isPending && <Spinner className="h-4 w-4 text-white" />}
            Count the answers
          </button>
        </Card>
      </div>

      <Card
        title={group?.label || "Tick all that apply"}
        subtitle={
          result
            ? `${result.row_count} option${result.row_count === 1 ? "" : "s"}, out of ` +
              `${formatNumber(result.total_rows_scanned ?? 0)} ${
                percentOf === "respondents" ? "who were asked" : "rows"
              }`
            : `${columns.length} column${columns.length === 1 ? "" : "s"} chosen`
        }
        actions={
          result &&
          canSave && (
            <button
              className="btn-primary btn-sm"
              onClick={() => setSaveOpen(true)}
            >
              {editing ? "Save changes" : "Save as chart"}
            </button>
          )
        }
      >
        {run.isPending ? (
          <Loading label="Counting the options" />
        ) : run.error ? (
          <ErrorNote error={run.error} />
        ) : !result ? (
          <EmptyState
            icon="◱"
            title="Nothing to show yet"
            description="Choose a question, or tick the 0/1 columns it was exported as, then count the answers."
          />
        ) : (
          <ChartCard
            result={result}
            chartType={chartType}
            height={Math.max(320, Math.min(720, result.row_count * 28 + 120))}
            display={display}
          />
        )}
      </Card>

      <SaveMultiSelectModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        datasetId={datasetId}
        datasetName={datasetName}
        chartType={chartType}
        display={display}
        request={body}
        defaultName={group?.label || group?.stem || "Tick all that apply"}
        editing={editing}
      />

      {naming && group && (
        <NameOptionsModal
          datasetId={datasetId}
          group={group}
          onClose={() => setNaming(false)}
        />
      )}
    </div>
  );
}

/**
 * Naming the options of a multiple-select, all of them at once.
 *
 * The option text is usually in the file - in the question's own value labels,
 * where the number after the underscores is the code - and it is read from
 * there on import. An export that carries none leaves the bars numbered, and
 * naming nineteen columns one at a time through the dataset's own label editor
 * is enough work that nobody does it. This writes the same thing that editor
 * writes: each column's variable label, which every chart, filter and table
 * then shows, and which survives the next export replacing the file.
 */
export function NameOptionsModal({
  datasetId,
  group,
  onClose,
}: {
  datasetId: string;
  group: MultiSelectGroup;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const options =
    group.options ?? group.columns.map((column) => ({ column, label: column }));
  // Blank where the name is only a number: that is a placeholder, not a name,
  // and offering it as the text to edit would have people saving "Option 8".
  const [names, setNames] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      options.map((option) => [
        option.column,
        option.label.startsWith("Option ") ? "" : option.label,
      ]),
    ),
  );

  const save = useMutation({
    mutationFn: async () => {
      const changed = options.filter(
        (option) =>
          (names[option.column] ?? "").trim() !==
          (option.label.startsWith("Option ") ? "" : option.label),
      );
      for (const option of changed) {
        await api.patch(
          `/datasets/${datasetId}/variables/${encodeURIComponent(option.column)}`,
          { label: (names[option.column] ?? "").trim() },
        );
      }
      return changed.length;
    },
    onSuccess: (changed) => {
      toast.push(
        changed
          ? `Named ${changed} option${changed === 1 ? "" : "s"}`
          : "Nothing changed",
        "success",
      );
      queryClient.invalidateQueries({
        queryKey: ["multiselect-groups", datasetId],
      });
      queryClient.invalidateQueries({ queryKey: ["dataset", datasetId] });
      queryClient.invalidateQueries({ queryKey: ["variables", datasetId] });
      onClose();
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  return (
    <Modal
      open
      onClose={onClose}
      title={`Name the options of ${group.label || group.stem}`}
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
            {save.isPending && <Spinner className="h-4 w-4 text-white" />}
            Save the names
          </button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-500">
        These are the words each option is drawn under, here and everywhere else
        this dataset is used. Leave one blank to leave it numbered.
      </p>
      <div className="max-h-96 space-y-1.5 overflow-y-auto pr-1">
        {options.map((option) => (
          <label key={option.column} className="flex items-center gap-2">
            <code
              className="w-40 shrink-0 truncate text-xs text-ink-500"
              title={option.column}
            >
              {option.column}
            </code>
            <input
              className="input py-1.5 text-sm"
              value={names[option.column] ?? ""}
              placeholder={option.label}
              onChange={(event) =>
                setNames({ ...names, [option.column]: event.target.value })
              }
            />
          </label>
        ))}
      </div>
    </Modal>
  );
}

export function SaveMultiSelectModal({
  open,
  onClose,
  datasetId,
  datasetName,
  chartType,
  display,
  request,
  defaultName,
  editing,
}: {
  open: boolean;
  onClose: () => void;
  datasetId: string;
  datasetName: string;
  chartType: ChartType;
  display: BuildOptions;
  request: MultiSelectRequest;
  defaultName: string;
  /** The saved chart being edited, updated rather than duplicated. */
  editing?: Chart;
}) {
  const toast = useToast();
  const [name, setName] = useState(editing?.name ?? "");

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name || editing?.name || defaultName,
        dataset_id: datasetId,
        chart_type: chartType,
        // The columns rather than a query: the server puts the question back
        // together when it renders the widget, so a dashboard filter still
        // reaches it.
        spec: { multiselect: request, options: display },
      };
      return editing
        ? api.patch(`/dashboards/charts/${editing.id}`, body)
        : api.post("/dashboards/charts", body);
    },
    onSuccess: () => {
      toast.push(
        editing ? "Chart updated" : "Chart saved; add it to a dashboard",
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
