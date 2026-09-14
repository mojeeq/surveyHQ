import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useEffect, useMemo, useRef, useState } from "react";

import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

import { api } from "@/lib/api";

import { useToast } from "@/hooks/useToast";

import type {
  Chart,
  DashboardSavedView,
  Dataset,
  DrillLevel,
  DrillStep,
  FilterGroup,
  Widget,
} from "@/lib/types";

import {
  controlKey,
  controlsForPage,
  filterableVariables,
  useDashboardDatasets,
  type FilterControl,
} from "@/components/DashboardFilters";

import { WidgetMenu } from "@/components/dashboard/WidgetMenu";
import { Loading, Modal } from "@/components/ui";

/** A selection made by clicking a mark, filtering the rest of the page.
 *
 *  `from` is the widget it was clicked on, which is left unfiltered: it is the
 *  thing being clicked, and collapsing it to the one bar just chosen would take
 *  away the means of choosing another.
 */
export type CrossFilter = {
  variable: string;
  value: string;
  label: string;
  from: string;
};

/** Fold a click-to-filter selection into the page's own filters. */
export function withCrossFilter(
  group: FilterGroup,
  picked: CrossFilter | null,
): FilterGroup {
  if (!picked) return group;
  return {
    ...group,
    conditions: [
      ...group.conditions,
      // The clicked text is the label shown on the axis, not the stored code.
      {
        variable: picked.variable,
        operator: "eq",
        value: picked.value,
        use_label: true,
      },
    ],
  };
}

/** Fold the path taken down the hierarchy into the page's filters.
 *
 *  Each step is the value clicked at that level, so drilling to Malampa then
 *  Central asks for the rows that are in both. The level itself does not
 *  travel here: it changes what the charts group on rather than which rows
 *  they count, and goes to the server as its own parameter.
 */
export function withDrillPath(
  group: FilterGroup,
  path: DrillStep[],
): FilterGroup {
  if (!path.length) return group;
  return {
    ...group,
    conditions: [
      ...group.conditions,
      ...path.map((step) => ({
        variable: step.variable,
        operator: "eq" as const,
        value: step.value,
        use_label: true,
      })),
    ],
  };
}

/** The variables of a board's hierarchy, outermost first. */
export const levelNames = (levels: DrillLevel[]): string[] =>
  levels.map((level) => level.variable).filter(Boolean);

/** What to call one level on the trail. */
export function levelLabel(levels: DrillLevel[], variable: string): string {
  const found = levels.find((level) => level.variable === variable);
  return found?.label || variable;
}

/** Whether clicking `variable` should go a level deeper rather than filter.
 *
 *  Only from the level the board is actually showing, and only while there is
 *  somewhere deeper to go. A click on the last level has nothing below it, so
 *  it filters instead - which is what a reader looking at one EA wants anyway.
 */
export function canDescend(
  levels: DrillLevel[],
  path: DrillStep[],
  variable: string,
): boolean {
  const names = levelNames(levels);
  const at = names.indexOf(variable);
  return at >= 0 && at === path.length && at < names.length - 1;
}

/** Where the reader is in the hierarchy, and the way back up.
 *
 *  Drawn as a trail rather than a "drill up" button because the question a
 *  manager asks next is usually two levels back, not one, and a trail can be
 *  clicked anywhere along its length.
 */
export function DrillTrail({
  levels,
  path,
  background,
  labelColor,
  onGoTo,
}: {
  levels: DrillLevel[];
  path: DrillStep[];
  /** The board's own filter-bar colours, so the two bands read as one strip. */
  background?: string;
  labelColor?: string;
  onGoTo: (depth: number) => void;
}) {
  const names = levelNames(levels);
  const showing = names[Math.min(path.length, names.length - 1)];
  const deeper = path.length < names.length - 1;
  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-card border border-ink-200 px-3 py-2 text-sm"
      // The band's own text colour, so the step you are standing on is
      // readable on a dark board. Without it the current step took the
      // default ink, which on a dark strip is all but invisible.
      style={{
        backgroundColor: background || "#ffffff",
        color: labelColor || undefined,
      }}
    >
      <span className="mr-1 text-xs font-medium uppercase tracking-wide opacity-80">
        Drill
      </span>
      <button
        className={
          path.length
            ? "rounded px-2 py-0.5 text-brand-500 hover:underline"
            : "rounded px-2 py-0.5 font-semibold"
        }
        disabled={!path.length}
        onClick={() => onGoTo(0)}
      >
        All
      </button>
      {path.map((step, index) => (
        <span
          key={`${step.variable}-${step.value}`}
          className="flex items-center gap-2"
        >
          <span className="opacity-50">/</span>
          <button
            className={
              index < path.length - 1
                ? "rounded px-2 py-0.5 text-brand-500 hover:underline"
                : "rounded px-2 py-0.5 font-semibold"
            }
            disabled={index === path.length - 1}
            title={`${step.label}: ${step.value}`}
            onClick={() => onGoTo(index + 1)}
          >
            {step.value}
          </button>
        </span>
      ))}
      <span className="ml-auto text-xs opacity-70">
        {deeper
          ? `Showing ${levelLabel(levels, showing)} - click a bar to go deeper`
          : `Showing ${levelLabel(levels, showing)} - the lowest level`}
      </span>
    </div>
  );
}

/** What to add to a widget's title when the board has drilled past its level.
 *
 *  Only when the chart actually moved: one grouped on something outside the
 *  hierarchy still says what its title says, and a chart already sitting at
 *  the level the board is showing was never renamed by the drill.
 */
export function drilledLevel(
  levels: DrillLevel[],
  path: DrillStep[],
  groupedOn: string[] | undefined,
): string | undefined {
  if (!path.length || !groupedOn?.length) return undefined;
  const names = levelNames(levels);
  const at = names.indexOf(groupedOn[0]);
  return at > 0 && at >= path.length
    ? levelLabel(levels, groupedOn[0])
    : undefined;
}

/** The variable a chart's first grouping is on, which is what a click means. */
export function clickedVariable(
  payload: { grouped_on?: string[] } | undefined,
): string {
  return payload?.grouped_on?.[0] ?? "";
}

/**
 * Chooses which variables the dashboard offers as filters.
 *
 * The candidates come from the datasets the dashboard's own widgets use, since
 * a filter on a variable nothing here carries would do nothing. Only
 * categorical variables with a manageable number of values are offered: a
 * dropdown of 40,000 interview keys is not a filter.
 */
/** The saved views bar: pick one, save the current selection, tidy up.
 *
 *  Deliberately a row of chips rather than a dropdown. A dropdown hides how
 *  many readings a board has and which one you are looking at, and the whole
 *  point of a view is to be one click from the board as it opens.
 */
export function SavedViews({
  basePath,
  dashboardId,
  isPublic,
  canPublish,
  current,
  activeId,
  labelColor,
  onApply,
}: {
  basePath: string;
  dashboardId: string;
  isPublic: boolean;
  canPublish: boolean;
  /** The board's filter-label colour, so the caption reads on a dark canvas. */
  labelColor?: string;
  /** The selection a new view would store: page, filters and drill path. */
  current: DashboardSavedView["state"];
  activeId: string;
  onApply: (view: DashboardSavedView) => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const key = ["dashboard-views", dashboardId, basePath];

  const views = useQuery({
    queryKey: key,
    queryFn: () => api.get<DashboardSavedView[]>(`${basePath}/views`),
  });

  const save = useMutation({
    mutationFn: (name: string) =>
      api.post<DashboardSavedView>(`/dashboards/${dashboardId}/views`, {
        name,
        state: current,
        is_shared: canPublish,
      }),
    onSuccess: (view) => {
      toast.push(`Saved "${view.name}"`, "success");
      queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const remove = useMutation({
    mutationFn: (view: DashboardSavedView) =>
      api.delete(`/dashboards/${dashboardId}/views/${view.id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const makeDefault = useMutation({
    mutationFn: (view: DashboardSavedView) =>
      api.patch(`/dashboards/${dashboardId}/views/${view.id}`, {
        is_default: true,
      }),
    onSuccess: () => {
      toast.push("This view is what the board opens on", "success");
      queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const saved = useMemo(() => views.data ?? [], [views.data]);

  // A board with a default view opens on it, once. After that the reader is
  // driving, and re-applying it would undo whatever they had just changed.
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || !saved.length) return;
    const fallback = saved.find((view) => view.is_default);
    opened.current = true;
    if (fallback) onApply(fallback);
    // onApply is rebuilt every render by the page above; depending on it here
    // would run this again on each one, which is the opposite of "once".
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved]);

  // Nothing saved and no way to save one: a reader of a link with no published
  // views has nothing this bar can offer, so it stays out of the way.
  if (!saved.length && isPublic) return null;

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <span
        className="text-xs font-medium uppercase tracking-wide text-ink-500"
        style={labelColor ? { color: labelColor } : undefined}
      >
        Views
      </span>
      {saved.map((view) => (
        <span key={view.id} className="flex items-center">
          <button
            className={`rounded-l-full border px-3 py-1 text-sm ${
              view.id === activeId
                ? "border-brand-500 bg-brand-500 text-white"
                : "border-slate-300 bg-white/70 text-slate-700 hover:bg-brand-50 dark:border-slate-600 dark:bg-slate-900/50 dark:text-slate-200 dark:hover:bg-slate-800"
            }`}
            title={view.description || `Open "${view.name}"`}
            onClick={() => onApply(view)}
          >
            {view.name}
            {view.is_default && (
              <span
                className="ml-1.5 text-xs opacity-70"
                title="Opens by default"
              >
                default
              </span>
            )}
          </button>
          {!isPublic && (
            <WidgetMenu
              label="⋯"
              always
              groups={[
                [
                  ...(canPublish && !view.is_default
                    ? [
                        {
                          label: "Open the board on this view",
                          onClick: () => makeDefault.mutate(view),
                        },
                      ]
                    : []),
                  {
                    label: "Delete this view",
                    danger: true,
                    onClick: () => {
                      if (confirm(`Delete the view "${view.name}"?`))
                        remove.mutate(view);
                    },
                  },
                ],
              ]}
            />
          )}
        </span>
      ))}
      {!isPublic && (
        <button
          className="rounded-full border border-dashed border-slate-400 px-3 py-1 text-sm text-slate-600 hover:border-brand-500 hover:text-brand-700 dark:text-slate-300"
          title="Save the filters, page and drill position you are looking at"
          onClick={() => {
            const name = prompt(
              'Name this view, e.g. "Malampa this week"',
            )?.trim();
            if (name) save.mutate(name);
          }}
        >
          + Save this view
        </button>
      )}
    </div>
  );
}

export function DrillDownModal({
  dashboardId,
  widgets,
  levels,
  onClose,
}: {
  dashboardId: string;
  /** Every widget on the board, so the levels come from datasets it uses. */
  widgets: Widget[];
  levels: DrillLevel[];
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<DrillLevel[]>(levels);

  const charts = useQuery({
    queryKey: ["charts"],
    queryFn: () => api.get<Chart[]>("/dashboards/charts"),
  });

  const datasetIds = useMemo(() => {
    const ids = new Set<string>();
    for (const widget of widgets) {
      if (widget.dataset_id) ids.add(widget.dataset_id);
      const chart = charts.data?.find((c) => c.id === widget.chart_id);
      if (chart) ids.add(chart.dataset_id);
    }
    return [...ids];
  }, [widgets, charts.data]);

  const details = useQuery({
    queryKey: ["dataset-details", datasetIds],
    queryFn: async () =>
      Promise.all(datasetIds.map((id) => api.get<Dataset>(`/datasets/${id}`))),
    enabled: datasetIds.length > 0,
  });

  /** Every variable the board could drill on, one entry per name.
   *
   *  By name rather than by dataset: a hierarchy is about the survey, not
   *  about one file, and "province" in the household file and in the person
   *  file are the same level. A chart whose dataset lacks a level simply does
   *  not follow the board that far down.
   */
  const candidates = useMemo(() => {
    const found = new Map<string, { name: string; label: string }>();
    for (const dataset of details.data ?? []) {
      for (const variable of filterableVariables(dataset)) {
        if (!found.has(variable.name)) {
          found.set(variable.name, {
            name: variable.name,
            label: variable.label || variable.name,
          });
        }
      }
    }
    return [...found.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [details.data]);

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/dashboards/${dashboardId}`, {
        drilldown: chosen.filter((level) => level.variable),
      }),
    onSuccess: () => {
      toast.push("Drill-down saved", "success");
      queryClient.invalidateQueries({ queryKey: ["dashboard", dashboardId] });
      onClose();
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const setLevel = (index: number, variable: string) => {
    const match = candidates.find((c) => c.name === variable);
    setChosen(
      chosen.map((level, at) =>
        at === index ? { variable, label: match?.label || variable } : level,
      ),
    );
  };

  const move = (index: number, by: number) => {
    const to = index + by;
    if (to < 0 || to >= chosen.length) return;
    const next = [...chosen];
    next.splice(to, 0, ...next.splice(index, 1));
    setChosen(next);
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Drill-down"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()}>
            Save drill-down
          </button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-500">
        Name the levels this board drills through, broadest first - province,
        then district, then enumeration area. Clicking a bar at one level
        narrows the whole page to what was clicked and regroups every chart at
        the next level down. A chart grouped on something outside this list
        keeps its own grouping and simply narrows.
      </p>

      {details.isLoading ? (
        <Loading />
      ) : !candidates.length ? (
        <p className="text-sm text-ink-500">
          Add a widget first; the levels come from the datasets the board uses.
        </p>
      ) : (
        <div className="space-y-2">
          {chosen.map((level, index) => (
            <div key={index} className="flex items-center gap-2">
              <span className="w-6 text-sm text-ink-400">{index + 1}.</span>
              <select
                className="input flex-1"
                value={level.variable}
                onChange={(event) => setLevel(index, event.target.value)}
              >
                <option value="">Choose a variable</option>
                {candidates.map((candidate) => (
                  <option key={candidate.name} value={candidate.name}>
                    {candidate.label}
                  </option>
                ))}
              </select>
              <button
                className="btn-ghost btn-sm"
                title="Move up"
                disabled={index === 0}
                onClick={() => move(index, -1)}
              >
                ▲
              </button>
              <button
                className="btn-ghost btn-sm"
                title="Move down"
                disabled={index === chosen.length - 1}
                onClick={() => move(index, 1)}
              >
                ▼
              </button>
              <button
                className="btn-ghost btn-sm text-danger-600"
                title="Remove this level"
                onClick={() =>
                  setChosen(chosen.filter((_, at) => at !== index))
                }
              >
                Remove
              </button>
            </div>
          ))}
          <button
            className="btn-secondary btn-sm"
            onClick={() => setChosen([...chosen, { variable: "", label: "" }])}
          >
            Add a level
          </button>
        </div>
      )}
    </Modal>
  );
}

export function FilterControlsModal({
  dashboardId,
  page,
  pageName,
  widgets,
  controls,
  onClose,
}: {
  dashboardId: string;
  /** The page whose filters are being chosen; each page has its own. */
  page: number;
  pageName: string;
  /** This page's widgets - the candidates come from what is actually on it. */
  widgets: Widget[];
  /** Every control on the dashboard, so the other pages' are kept on save. */
  controls: FilterControl[];
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<FilterControl[]>(() =>
    controlsForPage(controls, page),
  );

  const charts = useQuery({
    queryKey: ["charts"],
    queryFn: () => api.get<Chart[]>("/dashboards/charts"),
  });

  // A widget names either a chart (which names a dataset) or a dataset directly
  const datasetIds = useMemo(() => {
    const ids = new Set<string>();
    for (const widget of widgets) {
      if (widget.dataset_id) ids.add(widget.dataset_id);
      const chart = charts.data?.find((c) => c.id === widget.chart_id);
      if (chart) ids.add(chart.dataset_id);
    }
    return [...ids];
  }, [widgets, charts.data]);

  const datasets = useDashboardDatasets(datasetIds);
  const details = useQuery({
    queryKey: ["dataset-details", datasetIds],
    queryFn: async () =>
      Promise.all(datasetIds.map((id) => api.get<Dataset>(`/datasets/${id}`))),
    enabled: datasetIds.length > 0,
  });

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/dashboards/${dashboardId}`, {
        // Only this page's controls are being edited; the other pages keep
        // theirs, which is the whole point of filters being per page.
        filters: [
          ...controls.filter((control) => (control.page ?? 0) !== page),
          ...chosen.map((control) => ({ ...control, page })),
        ],
      }),
    onSuccess: () => {
      toast.push("Filters saved", "success");
      queryClient.invalidateQueries({ queryKey: ["dashboard", dashboardId] });
      onClose();
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const toggle = (control: FilterControl) => {
    const key = controlKey(control);
    const has = chosen.some((c) => controlKey(c) === key);
    setChosen(
      has ? chosen.filter((c) => controlKey(c) !== key) : [...chosen, control],
    );
  };

  /** Rename one control's label without disturbing which variable it filters. */
  const relabel = (control: FilterControl, label: string) => {
    const key = controlKey(control);
    setChosen(chosen.map((c) => (controlKey(c) === key ? { ...c, label } : c)));
  };

  /**
   * Chosen filters that this page can no longer offer a checkbox for.
   *
   * The candidates come from the datasets the page's widgets use, so a filter
   * outlives its candidacy: move the widget that brought its dataset here to
   * another page, delete it, or re-import so the variable has too many values
   * to be filterable, and the control is still stored and still drawn on the
   * bar - but there was no checkbox left to untick, and saving wrote it
   * straight back. It could not be removed at all. Listing it here is what
   * makes every stored filter reachable.
   */
  const offered = useMemo(() => {
    const keys = new Set<string>();
    for (const dataset of details.data ?? []) {
      for (const variable of filterableVariables(dataset)) {
        keys.add(
          controlKey({ dataset_id: dataset.id, variable: variable.name }),
        );
      }
    }
    return keys;
  }, [details.data]);

  const stranded = chosen.filter(
    (control) => !offered.has(controlKey(control)),
  );

  return (
    <Modal
      open
      onClose={onClose}
      title={`Filters on "${pageName}"`}
      wide
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()}>
            Save filters
          </button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-500">
        These filters appear on this page only; every page has its own. A filter
        narrows each widget whose dataset carries the variable and says so on
        any widget it could not reach - the variables below are the ones this
        page's own datasets have.
      </p>

      {details.isLoading || datasets.isLoading ? (
        <Loading />
      ) : !details.data?.length ? (
        <p className="text-sm text-ink-500">
          Add a widget to this page first; the filters come from the datasets it
          uses.
        </p>
      ) : (
        <div className="space-y-4">
          {details.data.map((dataset) => {
            const options = filterableVariables(dataset);
            return (
              <div key={dataset.id}>
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  {dataset.name}
                </p>
                {!options.length ? (
                  <p className="mt-1 text-sm text-ink-400">
                    No variable here has few enough values to filter by.
                  </p>
                ) : (
                  <div className="mt-1 grid gap-1 sm:grid-cols-2">
                    {options.map((variable) => (
                      <FilterChoice
                        key={variable.name}
                        variable={variable}
                        datasetId={dataset.id}
                        chosen={chosen}
                        onToggle={toggle}
                        onRelabel={relabel}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {stranded.length > 0 && (
        <div className="aero-pane aero-pane-warn mt-4 p-3 pl-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-900 dark:text-amber-200">
            Still on this page, but nothing here uses them
          </p>
          <p className="mt-1 text-sm text-amber-800">
            These filters are still drawn on the bar, but the data they came
            from has left this page - the widget that brought it was moved or
            removed, or the variable now has too many values to filter by.
          </p>
          <ul className="mt-2 space-y-1">
            {stranded.map((control) => (
              <li
                key={controlKey(control)}
                className="flex items-center justify-between gap-3 text-sm text-ink-700"
              >
                <span className="truncate">
                  {control.label || control.variable}
                  <span className="text-ink-400"> ({control.variable})</span>
                </span>
                <button
                  className="btn-ghost btn-sm text-red-600"
                  onClick={() => toggle(control)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Modal>
  );
}

/**
 * One variable offered as a filter, with the name its control will carry.
 *
 * The bar used to print the raw column name, so a dashboard built for a
 * minister said "hh_prov_cd" above the dropdown. The label defaults to the
 * variable's own label where the data has one and to its name otherwise, and
 * can be typed over: what a filter is called on a dashboard is a presentation
 * decision, not a property of the column.
 */
export function FilterChoice({
  variable,
  datasetId,
  chosen,
  onToggle,
  onRelabel,
}: {
  variable: { name: string; label?: string; n_unique: number };
  datasetId: string;
  chosen: FilterControl[];
  onToggle: (control: FilterControl) => void;
  onRelabel: (control: FilterControl, label: string) => void;
}) {
  const control: FilterControl = {
    variable: variable.name,
    dataset_id: datasetId,
    label: variable.label || variable.name,
  };
  const key = controlKey(control);
  const picked = chosen.find((c) => controlKey(c) === key);

  return (
    <div className="flex items-center gap-2 text-sm text-ink-700">
      <label className="flex min-w-0 flex-1 items-center gap-2">
        <input
          type="checkbox"
          checked={Boolean(picked)}
          onChange={() => onToggle(control)}
        />
        <span className="truncate">
          {variable.label
            ? `${variable.name} - ${variable.label}`
            : variable.name}
          <span className="text-ink-400"> ({variable.n_unique})</span>
        </span>
      </label>
      {picked && (
        <input
          className="input h-7 w-36 shrink-0 py-0 text-xs"
          aria-label={`Label for the ${variable.name} filter`}
          title="What this filter is called on the dashboard"
          value={picked.label ?? ""}
          placeholder={variable.name}
          onChange={(event) => onRelabel(control, event.target.value)}
        />
      )}
    </div>
  );
}
