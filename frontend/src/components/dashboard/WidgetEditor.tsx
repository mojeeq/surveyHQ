import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useState } from "react";

import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

import { api } from "@/lib/api";

import { useToast } from "@/hooks/useToast";

import type {
  BoundaryLayer,
  Chart,
  Dataset,
  Indicator,
  Page,
  Widget,
} from "@/lib/types";

import ColorPicker from "@/components/ColorPicker";

import HtmlLibrary from "@/components/HtmlLibrary";

import {
  BASEMAP_NAMES,
  BASEMAPS,
  DEFAULT_POINT_OPACITY,
  DEFAULT_POINT_SIZE,
  DEFAULT_TILES,
  POINT_ICON_NAMES,
  POINT_ICONS,
} from "@/components/MapWidget";

import { FONTS, fontFor } from "@/lib/fonts";

import {
  DEFAULT_TITLE_SIZE,
  panelDefault,
} from "@/components/dashboard/shared";
import { Field, Loading, Modal, Section, useOpenSections } from "@/components/ui";
import { PER_CHECK_VIEWS, QUALITY_CHARTS, qualityChartType } from "@/lib/quality";

/** Whether this dataset looks like it has a GPS reading the map cannot offer.
 *
 * The Latitude and Longitude lists hold numeric variables only. A reading that
 * arrived as one column of text - "lat lon altitude accuracy" out of ODK, say -
 * is therefore in the dataset and not in the list, which reads as the platform
 * having lost it. Import splits such a column now, so the answer is to import
 * the file again; this says so where the empty list is.
 */
/** The widget kinds, for the picker and for naming one in a folded section. */
const WIDGET_KINDS: { value: string; label: string }[] = [
  { value: "chart", label: "Saved chart or cross-tab" },
  { value: "indicator", label: "Indicator tile" },
  { value: "quality", label: "Data quality panel" },
  { value: "text", label: "Text note" },
  { value: "countdown", label: "Countdown to a date" },
  { value: "map", label: "Map of interview locations" },
  { value: "html", label: "Embedded HTML" },
  { value: "freshness", label: "How recent the data is" },
];

function looksLikeAnUnsplitGps(
  variables: { name: string; var_type: string }[],
): boolean {
  const words = (name: string) => name.toLowerCase().split(/[^a-z0-9]+/);
  const hasCoordinate = variables.some(
    (v) =>
      v.var_type === "numeric" &&
      words(v.name).some((w) => w === "latitude" || w === "lat"),
  );
  if (hasCoordinate) return false;
  return variables.some(
    (v) =>
      v.var_type !== "numeric" &&
      words(v.name).some((w) =>
        ["gps", "geopoint", "gpspoint", "location", "coordinates", "latlon"].includes(w),
      ),
  );
}

/**
 * The two questions a data quality panel asks: what to plot, and how to draw it.
 *
 * One component because the new-widget form and the edit form ask them
 * identically; they differ only in where the answer is kept, which is what the
 * patch handed back is for.
 *
 * The chart is not cleared when the view changes. A panel moved from rows
 * flagged to failure rates cannot stay a donut - rates are not parts of a
 * whole, so that view does not offer one - but moving back should not have
 * cost the choice, and `qualityChartType` draws the view's own default in the
 * meantime.
 */
function QualityForm({
  view,
  chart,
  limit,
  onChange,
}: {
  view: string;
  chart: string;
  limit: string;
  onChange: (patch: {
    quality_view?: string;
    quality_chart?: string;
    quality_limit?: number;
  }) => void;
}) {
  const offered = QUALITY_CHARTS[view] ?? [];
  return (
    <>
      <Field
        label="Show it as"
        hint="A panel of findings reads at a desk; a chart reads from across a room, a line says whether it is getting better, and the mix says in one shape whether this dataset is in order."
      >
        <select
          className="input"
          value={view}
          onChange={(event) => onChange({ quality_view: event.target.value })}
        >
          <option value="list">The findings, listed</option>
          <option value="rate">Share of rows failing</option>
          <option value="rows">How many rows flagged</option>
          <option value="trend">Failure rate over time</option>
          <option value="rows_trend">Rows flagged over time</option>
          <option value="mix">Passing, failing and never run</option>
        </select>
      </Field>
      {offered.length > 1 && (
        <Field
          label="Drawn as"
          hint="Bars compare the checks against each other; a share says how the flagged rows divide between them; a table is for reading the numbers off."
        >
          <select
            className="input"
            value={qualityChartType(view, chart)}
            onChange={(event) => onChange({ quality_chart: event.target.value })}
          >
            {offered.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
      )}
      {PER_CHECK_VIEWS.has(view) && (
        <Field
          label="Draw at most"
          hint="A dataset with forty checks on it draws forty bars, and on a widget that is forty slivers with no room for a name against any of them. The worst few are the ones acted on. Blank draws them all, and the counts above the chart go on counting every check either way."
        >
          <input
            className="input"
            type="number"
            min={0}
            step={1}
            placeholder="Every check"
            value={limit}
            onChange={(event) =>
              onChange({ quality_limit: Math.max(0, Number(event.target.value) || 0) })
            }
          />
        </Field>
      )}
    </>
  );
}

const UNSPLIT_GPS_HINT =
  "No numeric coordinate in this dataset. If the reading is one column of " +
  "text, like \"-17.7333 168.3273 42.0 5.0\", import the file again: it is " +
  "then split into __latitude and __longitude columns that appear here.";

export function AddWidgetModal({
  dashboardId,
  projectId,
  page,
  onClose,
}: {
  dashboardId: string;
  /** The dashboard's project, so the picker offers its charts and not every
   *  chart on the platform. Null is the shared area, which is its own place. */
  projectId: string | null;
  /** The page being looked at, which is where a new widget belongs. */
  page: number;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<
    | "chart"
    | "indicator"
    | "quality"
    | "text"
    | "countdown"
    | "map"
    | "html"
    | "freshness"
  >("chart");
  const [datasetId, setDatasetId] = useState("");
  const [chartId, setChartId] = useState("");
  const [indicatorId, setIndicatorId] = useState("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [deadline, setDeadline] = useState("");
  const [deadlineLabel, setDeadlineLabel] = useState("");
  const [caption, setCaption] = useState("");
  const [showBreakdown, setShowBreakdown] = useState(true);
  const [showTrend, setShowTrend] = useState(true);
  /** Which form a new quality panel opens in, and how that form is drawn. */
  const [qualityView, setQualityView] = useState("list");
  const [qualityChart, setQualityChart] = useState("");
  const [qualityLimit, setQualityLimit] = useState(0);
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [measureAgg, setMeasureAgg] = useState("count");
  const [measureVariable, setMeasureVariable] = useState("");
  const [detail, setDetail] = useState<string[]>([]);
  const [tiles, setTiles] = useState("");
  const [basemap, setBasemap] = useState("streets");
  const [html, setHtml] = useState("");
  const [freshnessDatasets, setFreshnessDatasets] = useState<string[]>([]);

  // A dashboard about one round has no use for another round's charts, and a
  // list of everything is where the right one gets lost. A dashboard in the
  // shared area belongs to no project, so there is nothing to narrow to and it
  // goes on seeing everything the user can.
  const scope = projectId ? `&project_id=${projectId}` : "";
  const charts = useQuery({
    queryKey: ["charts", projectId],
    queryFn: () => api.get<Chart[]>(`/dashboards/charts?${scope.slice(1)}`),
  });
  const indicators = useQuery({
    queryKey: ["indicators", projectId],
    queryFn: () =>
      api.get<Indicator[]>(`/monitoring/indicators?${scope.slice(1)}`),
  });
  const datasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => api.get<Page<Dataset>>(`/datasets?limit=200${scope}`),
    enabled: kind === "quality" || kind === "map" || kind === "freshness",
  });
  // The map needs the variables, to know which column holds the coordinates.
  const chosenDataset = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: kind === "map" && Boolean(datasetId),
  });

  const add = useMutation({
    mutationFn: () =>
      api.post(`/dashboards/${dashboardId}/widgets`, {
        title:
          title ||
          (kind === "chart"
            ? charts.data?.find((c) => c.id === chartId)?.name
            : kind === "quality"
              ? `Data quality: ${datasets.data?.items.find((d) => d.id === datasetId)?.name ?? ""}`
              : kind === "map"
                ? "Interview locations"
                : kind === "html"
                  ? "Embedded content"
                  : kind === "freshness"
                    ? "Data freshness"
                    : kind === "countdown"
                      ? deadlineLabel || "Countdown"
                      : indicators.data?.find((i) => i.id === indicatorId)
                          ?.name) ||
          "Widget",
        widget_type: kind,
        chart_id: kind === "chart" ? chartId : null,
        indicator_id: kind === "indicator" ? indicatorId : null,
        dataset_id: kind === "quality" || kind === "map" ? datasetId : null,
        page,
        config: {
          ...(kind === "map"
            ? {
                latitude,
                longitude,
                measure_agg: measureAgg,
                measure_variable: measureAgg === "count" ? "" : measureVariable,
                detail,
                ...(tiles.trim() ? { tiles: tiles.trim() } : {}),
                ...(basemap !== "streets" ? { basemap } : {}),
              }
            : kind === "freshness"
              ? {
                  dataset_ids: freshnessDatasets,
                  warn_hours: 24,
                  critical_hours: 72,
                }
              : kind === "html"
                ? { html }
                : kind === "quality"
                  ? {
                      quality_view: qualityView,
                      ...(qualityChart ? { quality_chart: qualityChart } : {}),
                      ...(qualityLimit ? { quality_limit: qualityLimit } : {}),
                    }
                  : kind === "indicator"
                    ? { show_breakdown: showBreakdown, show_trend: showTrend }
                    : kind === "text"
                      ? { content }
                      : kind === "countdown"
                        ? // A local datetime from the browser; sent as an instant so the
                          // count reads the same wherever the dashboard is opened.
                          {
                            target: new Date(deadline).toISOString(),
                            label: deadlineLabel,
                          }
                        : {}),
          ...(caption.trim() ? { caption: caption.trim() } : {}),
        },
        layout:
          kind === "map"
            ? { w: 6, h: 6 }
            : kind === "freshness"
              ? { w: 4, h: 4 }
              : kind === "countdown"
                ? { w: 3, h: 3 }
                : kind === "indicator"
                  ? // A tile with a chart under it needs the room for one.
                    showBreakdown && chosenIndicator?.breakdown_variable
                    ? { w: 4, h: 5 }
                    : { w: 3, h: 3 }
                  : { w: 6, h: 4 },
      }),
    onSuccess: () => {
      toast.push("Widget added", "success");
      queryClient.invalidateQueries({ queryKey: ["dashboard", dashboardId] });
      queryClient.invalidateQueries({
        queryKey: ["dashboard-data", dashboardId],
      });
      onClose();
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const chosenIndicator = indicators.data?.find((i) => i.id === indicatorId);
  const numericVariables = (chosenDataset.data?.variables ?? []).filter(
    (v) => v.var_type === "numeric",
  );

  const canAdd =
    (kind === "chart" && chartId) ||
    (kind === "indicator" && indicatorId) ||
    (kind === "quality" && datasetId) ||
    (kind === "text" && content) ||
    (kind === "countdown" && deadline && !Number.isNaN(Date.parse(deadline))) ||
    (kind === "map" && datasetId && latitude && longitude) ||
    (kind === "html" && html.trim()) ||
    (kind === "freshness" && freshnessDatasets.length);

  return (
    <Modal
      open
      onClose={onClose}
      title="Add a widget"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => add.mutate()}
            disabled={!canAdd}
          >
            Add widget
          </button>
        </>
      }
    >
      <Field label="Widget type">
        <select
          className="input"
          value={kind}
          onChange={(event) => setKind(event.target.value as typeof kind)}
        >
          {WIDGET_KINDS.map((one) => (
            <option key={one.value} value={one.value}>
              {one.label}
            </option>
          ))}
        </select>
      </Field>

      {kind === "chart" && (
        <Field label="Chart or cross-tab">
          <select
            className="input"
            value={chartId}
            onChange={(event) => setChartId(event.target.value)}
          >
            <option value="">Choose a saved chart…</option>
            {charts.data?.map((chart) => (
              <option key={chart.id} value={chart.id}>
                {/* Two saved items can share a name while rendering quite
                    differently, so say which kind each one is. */}
                {chart.name} (
                {chart.chart_type === "crosstab"
                  ? "cross-tab"
                  : chart.chart_type}
                )
              </option>
            ))}
          </select>
        </Field>
      )}

      {kind === "quality" && (
        <Field
          label="Dataset"
          hint="Shows the state of that dataset's active checks as of their last run."
        >
          <select
            className="input"
            value={datasetId}
            onChange={(event) => setDatasetId(event.target.value)}
          >
            <option value="">Choose a dataset…</option>
            {datasets.data?.items.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      {kind === "quality" && (
        <QualityForm
          view={qualityView}
          chart={qualityChart}
          limit={qualityLimit ? String(qualityLimit) : ""}
          onChange={(patch) => {
            if (patch.quality_view !== undefined) setQualityView(patch.quality_view);
            if (patch.quality_chart !== undefined)
              setQualityChart(patch.quality_chart);
            if (patch.quality_limit !== undefined)
              setQualityLimit(patch.quality_limit);
          }}
        />
      )}

      {kind === "indicator" && (
        <>
          <Field label="Indicator">
            <select
              className="input"
              value={indicatorId}
              onChange={(event) => setIndicatorId(event.target.value)}
            >
              <option value="">Choose an indicator…</option>
              {indicators.data?.map((indicator) => (
                <option key={indicator.id} value={indicator.id}>
                  {indicator.name}
                </option>
              ))}
            </select>
          </Field>
          {chosenIndicator?.breakdown_variable && (
            <label className="mb-4 flex items-center gap-2 text-sm text-ink-700">
              <input
                type="checkbox"
                checked={showBreakdown}
                onChange={(event) => setShowBreakdown(event.target.checked)}
              />
              Show the breakdown by {chosenIndicator.breakdown_variable} under
              the number
            </label>
          )}
          <label className="mb-4 flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={showTrend}
              onChange={(event) => setShowTrend(event.target.checked)}
            />
            Draw a trend line from the stored runs
          </label>
        </>
      )}

      {kind === "map" && (
        <>
          <Field
            label="Dataset"
            hint="The one holding the GPS question - usually the interview level."
          >
            <select
              className="input"
              value={datasetId}
              onChange={(event) => {
                setDatasetId(event.target.value);
                setLatitude("");
                setLongitude("");
                setDetail([]);
              }}
            >
              <option value="">Choose a dataset…</option>
              {datasets.data?.items.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </select>
          </Field>

          {chosenDataset.isLoading ? (
            <Loading />
          ) : chosenDataset.data ? (
            <>
              <div className="grid gap-x-4 sm:grid-cols-2">
                <Field label="Latitude">
                  <select
                    className="input"
                    value={latitude}
                    onChange={(event) => setLatitude(event.target.value)}
                  >
                    <option value="">Choose…</option>
                    {numericVariables.map((v) => (
                      <option key={v.name} value={v.name}>
                        {v.label ? `${v.name} - ${v.label}` : v.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Longitude">
                  <select
                    className="input"
                    value={longitude}
                    onChange={(event) => setLongitude(event.target.value)}
                  >
                    <option value="">Choose…</option>
                    {numericVariables.map((v) => (
                      <option key={v.name} value={v.name}>
                        {v.label ? `${v.name} - ${v.label}` : v.name}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              {looksLikeAnUnsplitGps(chosenDataset.data.variables ?? []) && (
                <p className="-mt-2 mb-3 text-xs text-slate-500">
                  {UNSPLIT_GPS_HINT}
                </p>
              )}

              <Field
                label="What each pin counts"
                hint="Records at the same coordinate are one pin. This is the number it carries."
              >
                <div className="flex gap-2">
                  <select
                    className="input w-56"
                    value={measureAgg}
                    onChange={(event) => setMeasureAgg(event.target.value)}
                  >
                    <option value="count">How many records</option>
                    <option value="sum">Total of</option>
                    <option value="mean">Average of</option>
                    <option value="max">Highest</option>
                    <option value="min">Lowest</option>
                  </select>
                  {measureAgg !== "count" && (
                    <select
                      className="input"
                      value={measureVariable}
                      onChange={(event) =>
                        setMeasureVariable(event.target.value)
                      }
                    >
                      <option value="">Choose a variable…</option>
                      {numericVariables.map((v) => (
                        <option key={v.name} value={v.name}>
                          {v.label ? `${v.name} - ${v.label}` : v.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              </Field>

              <Field
                label="Base map"
                hint="The ground the pins sit on. A reader can switch it on the map itself."
              >
                <select
                  className="input"
                  value={basemap}
                  onChange={(event) => setBasemap(event.target.value)}
                >
                  {BASEMAP_NAMES.map((name) => (
                    <option key={name} value={name}>
                      {BASEMAPS[name].label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field
                label="Map tiles"
                hint="Leave blank for the base map above. A server with no internet can point this at its own tile service."
              >
                <input
                  className="input font-mono text-xs"
                  value={tiles}
                  onChange={(event) => setTiles(event.target.value)}
                  placeholder={DEFAULT_TILES}
                />
              </Field>

              <Field
                label="Show on click"
                hint="Up to six variables, listed in the popup when a pin is clicked."
              >
                <div className="grid max-h-40 gap-1 overflow-auto sm:grid-cols-2">
                  {(chosenDataset.data.variables ?? [])
                    .filter((v) => !v.is_hidden)
                    .slice(0, 300)
                    .map((v) => (
                      <label
                        key={v.name}
                        className="flex items-center gap-2 text-sm text-ink-700"
                      >
                        <input
                          type="checkbox"
                          checked={detail.includes(v.name)}
                          disabled={
                            !detail.includes(v.name) && detail.length >= 6
                          }
                          onChange={() =>
                            setDetail(
                              detail.includes(v.name)
                                ? detail.filter((name) => name !== v.name)
                                : [...detail, v.name],
                            )
                          }
                        />
                        <span className="truncate">{v.label || v.name}</span>
                      </label>
                    ))}
                </div>
              </Field>
            </>
          ) : null}
        </>
      )}

      {kind === "freshness" && (
        <FreshnessFields
          datasets={datasets.data?.items ?? []}
          config={{ dataset_ids: freshnessDatasets }}
          onChange={(patch) =>
            patch.dataset_ids &&
            setFreshnessDatasets(patch.dataset_ids as string[])
          }
        />
      )}

      {kind === "html" && (
        <Field
          label="HTML"
          hint="Rendered in a sandboxed frame, so it cannot reach the rest of the page."
        >
          <HtmlLibrary html={html} projectId={projectId} onLoad={setHtml} />
          <textarea
            className="input font-mono text-xs"
            rows={8}
            value={html}
            onChange={(event) => setHtml(event.target.value)}
            placeholder={
              "<h2>Round 3</h2>\n<p>Enumeration closes on Friday.</p>"
            }
          />
        </Field>
      )}

      {kind === "countdown" && (
        <>
          <Field
            label="Counting down to"
            hint="Fieldwork closing, a reporting deadline."
          >
            <input
              type="datetime-local"
              className="input"
              value={deadline}
              onChange={(event) => setDeadline(event.target.value)}
            />
          </Field>
          <Field label="Caption" hint="Shown under the clock.">
            <input
              className="input"
              value={deadlineLabel}
              onChange={(event) => setDeadlineLabel(event.target.value)}
              placeholder="until fieldwork closes"
            />
          </Field>
        </>
      )}

      {kind === "text" && (
        <Field label="Text">
          <textarea
            className="input"
            rows={4}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="Notes, context or instructions for whoever reads this dashboard."
          />
        </Field>
      )}

      <Field
        label="Title"
        hint="Leave blank to use the chart or indicator name"
      >
        <input
          className="input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </Field>

      <Field
        label="Caption"
        hint="Optional. Shown under the widget - a sentence saying what the reader is looking at."
      >
        <textarea
          className="input text-sm"
          rows={2}
          value={caption}
          placeholder="Completed interviews only. Excludes the pilot round."
          onChange={(event) => setCaption(event.target.value)}
        />
      </Field>
    </Modal>
  );
}

/**
 * Everything about a widget that is already on the board.
 *
 * Before this, a widget was fixed once added: a countdown pointing at last
 * month's deadline, or a map on the wrong coordinate column, had to be deleted
 * and built again, losing its place in the layout.
 *
 * Its kind is the one thing not editable here. A chart widget and a map widget
 * have nothing in common but a title, so turning one into the other is adding
 * a different widget rather than editing this one.
 */
export function EditWidgetModal({
  dashboardId,
  projectId,
  widget,
  pageNames,
  dashboardOpacity,
  onClose,
}: {
  dashboardId: string;
  /** The dashboard's project: the same set of charts the picker offered. */
  projectId: string | null;
  widget: Widget;
  pageNames: string[];
  /** What this widget's transparency falls back to when it sets none. */
  dashboardOpacity: number;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(widget.title ?? "");
  const [page, setPage] = useState(widget.page ?? 0);
  const [width, setWidth] = useState(Number(widget.layout?.w ?? 6));
  const [height, setHeight] = useState(Number(widget.layout?.h ?? 4));
  const [config, setConfig] = useState<Record<string, any>>({
    ...(widget.config ?? {}),
  });
  const [chartId, setChartId] = useState(widget.chart_id ?? "");
  const [indicatorId, setIndicatorId] = useState(widget.indicator_id ?? "");
  const [datasetId, setDatasetId] = useState(widget.dataset_id ?? "");

  const kind = widget.widget_type;
  const set = (patch: Record<string, any>) =>
    setConfig({ ...config, ...patch });

  // What it shows is open to begin with, because that is what somebody opening
  // a widget usually came to change. The other two say what they hold on their
  // closed row, so nothing has to be opened to be found.
  const [open, toggle] = useOpenSections("widget", ["content"]);

  /** A few words per section, for when it is closed. */
  const summaries = {
    basics: [
      title.trim() || "Untitled",
      `page ${(pageNames[page] ?? page + 1).toString()}`,
      config.caption ? "captioned" : "",
    ]
      .filter(Boolean)
      .join(", "),
    content: WIDGET_KINDS.find((k) => k.value === kind)?.label ?? String(kind),
    boundaries: [
      config.boundary_id ? "a layer" : "none chosen",
      config.boundary_label ? "labelled" : "",
      config.area_variable ? "area checked" : "",
    ]
      .filter(Boolean)
      .join(", "),
    look: [
      config.background ? "colour" : "",
      config.opacity !== undefined
        ? `${Math.round(config.opacity * 100)}% opaque`
        : "",
      config.font_family ? fontFor(config.font_family)?.label ?? "own font" : "",
      config.title_font ? FONTS.find((f) => f.id === config.title_font)?.label ?? "" : "",
      config.title_size ? `${config.title_size}px title` : "",
      config.series_color ? "chart colour" : "",
    ]
      .filter(Boolean)
      .join(", "),
  };

  const charts = useQuery({
    queryKey: ["charts", projectId],
    queryFn: () =>
      api.get<Chart[]>(
        `/dashboards/charts${projectId ? `?project_id=${projectId}` : ""}`,
      ),
    enabled: kind === "chart",
  });
  const indicators = useQuery({
    queryKey: ["indicators", projectId],
    queryFn: () =>
      api.get<Indicator[]>(
        `/monitoring/indicators${projectId ? `?project_id=${projectId}` : ""}`,
      ),
    enabled: kind === "indicator",
  });
  const datasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () =>
      api.get<Page<Dataset>>(
        `/datasets?limit=200${projectId ? `&project_id=${projectId}` : ""}`,
      ),
    enabled: kind === "quality" || kind === "map" || kind === "freshness",
  });
  const mapDataset = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: kind === "map" && Boolean(datasetId),
  });
  const boundaries = useQuery({
    queryKey: ["boundaries", projectId],
    queryFn: () =>
      api.get<BoundaryLayer[]>(
        `/boundaries${projectId ? `?project_id=${projectId}` : ""}`,
      ),
    enabled: kind === "map",
  });
  // The attributes of whichever layer is chosen, so the two dropdowns below
  // offer its own column names rather than asking anyone to type them.
  const boundaryProperties =
    boundaries.data?.find((item) => item.id === config.boundary_id)
      ?.properties ?? [];

  const save = useMutation({
    mutationFn: () =>
      // One widget, through the endpoint that changes one widget - references
      // included. This used to need a second call through the whole-dashboard
      // PATCH, which takes the complete widget list and deletes whatever is
      // missing from it: sending the single widget being edited wiped every
      // other widget on every page, which is what "changing a graph made all
      // my widgets disappear" was.
      api.patch(`/dashboards/${dashboardId}/widgets/${widget.id}`, {
        title,
        page,
        config: {
          ...config,
          ...(kind === "map" || kind === "quality"
            ? { dataset_id: datasetId }
            : {}),
        },
        // Sent whole, so a resize here lands the same way a drag does.
        layout: { ...(widget.layout ?? {}), w: width, h: height },
        ...(kind === "chart" ? { chart_id: chartId || null } : {}),
        ...(kind === "indicator" ? { indicator_id: indicatorId || null } : {}),
        ...(kind === "quality" || kind === "map"
          ? { dataset_id: datasetId || null }
          : {}),
      }),
    onSuccess: () => {
      toast.push("Widget updated", "success");
      queryClient.invalidateQueries({ queryKey: ["dashboard", dashboardId] });
      queryClient.invalidateQueries({
        queryKey: ["dashboard-data", dashboardId],
      });
      onClose();
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const numericVariables = (mapDataset.data?.variables ?? []).filter(
    (v) => v.var_type === "numeric",
  );

  return (
    <Modal
      open
      onClose={onClose}
      title={`Edit "${widget.title || widget.widget_type}"`}
      wide
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
            Save changes
          </button>
        </>
      }
    >
      <Section title="Basics" summary={summaries.basics} open={open.has('basics')} onToggle={(o) => toggle('basics', o)}>
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="Title">
          <input
            className="input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <Field label="Page">
          <select
            className="input"
            value={page}
            onChange={(event) => setPage(Number(event.target.value))}
          >
            {pageNames.map((name, index) => (
              <option key={index} value={index}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Width (columns)">
          <input
            className="input"
            type="number"
            min={1}
            max={24}
            value={width}
            onChange={(event) => setWidth(Number(event.target.value) || 1)}
          />
        </Field>
        <Field label="Height (rows)">
          <input
            className="input"
            type="number"
            min={1}
            max={24}
            value={height}
            onChange={(event) => setHeight(Number(event.target.value) || 1)}
          />
        </Field>
      </div>

      <Field
        label="Caption"
        hint="Shown under the widget. A sentence saying what the reader is looking at, or where the number comes from."
      >
        <textarea
          className="input text-sm"
          rows={2}
          value={config.caption ?? ""}
          placeholder="Completed interviews only. Excludes the pilot round."
          onChange={(event) =>
            set({ caption: event.target.value || undefined })
          }
        />
      </Field>
      </Section>

      <Section title="What it shows" summary={summaries.content} open={open.has('content')} onToggle={(o) => toggle('content', o)}>
      {kind === "chart" && (
        <Field label="Chart">
          <select
            className="input"
            value={chartId}
            onChange={(event) => setChartId(event.target.value)}
          >
            {charts.data?.map((chart) => (
              <option key={chart.id} value={chart.id}>
                {chart.name} (
                {chart.chart_type === "crosstab"
                  ? "cross-tab"
                  : chart.chart_type}
                )
              </option>
            ))}
          </select>
        </Field>
      )}

      {kind === "indicator" && (
        <>
          <Field label="Indicator">
            <select
              className="input"
              value={indicatorId}
              onChange={(event) => setIndicatorId(event.target.value)}
            >
              {indicators.data?.map((indicator) => (
                <option key={indicator.id} value={indicator.id}>
                  {indicator.name}
                </option>
              ))}
            </select>
          </Field>
          <label className="mb-4 flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={Boolean(config.show_breakdown)}
              onChange={(event) =>
                set({ show_breakdown: event.target.checked })
              }
            />
            Show the breakdown chart under the number
          </label>
          <label className="mb-4 flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={Boolean(config.show_trend)}
              onChange={(event) => set({ show_trend: event.target.checked })}
            />
            Draw a trend line from the stored runs
          </label>
        </>
      )}

      {(kind === "quality" || kind === "map") && (
        <Field label="Dataset">
          <select
            className="input"
            value={datasetId}
            onChange={(event) => setDatasetId(event.target.value)}
          >
            <option value="">Choose a dataset…</option>
            {datasets.data?.items.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      {kind === "quality" && (
        <QualityForm
          view={String(config.quality_view ?? "list")}
          chart={String(config.quality_chart ?? "")}
          limit={config.quality_limit ? String(config.quality_limit) : ""}
          onChange={set}
        />
      )}

      {kind === "map" && (
        <>
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="Latitude">
              <select
                className="input"
                value={config.latitude ?? ""}
                onChange={(event) => set({ latitude: event.target.value })}
              >
                <option value="">Choose…</option>
                {numericVariables.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Longitude">
              <select
                className="input"
                value={config.longitude ?? ""}
                onChange={(event) => set({ longitude: event.target.value })}
              >
                <option value="">Choose…</option>
                {numericVariables.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {looksLikeAnUnsplitGps(mapDataset.data?.variables ?? []) && (
            <p className="-mt-2 mb-3 text-xs text-slate-500">
              {UNSPLIT_GPS_HINT}
            </p>
          )}
          <Field label="What each pin counts">
            <div className="flex gap-2">
              <select
                className="input w-56"
                value={config.measure_agg ?? "count"}
                onChange={(event) => set({ measure_agg: event.target.value })}
              >
                <option value="count">How many records</option>
                <option value="sum">Total of</option>
                <option value="mean">Average of</option>
                <option value="max">Highest</option>
                <option value="min">Lowest</option>
              </select>
              {(config.measure_agg ?? "count") !== "count" && (
                <select
                  className="input"
                  value={config.measure_variable ?? ""}
                  onChange={(event) =>
                    set({ measure_variable: event.target.value })
                  }
                >
                  <option value="">Choose a variable…</option>
                  {numericVariables.map((v) => (
                    <option key={v.name} value={v.name}>
                      {v.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </Field>
        </>
      )}

      {kind === "text" && (
        <Field label="Text">
          <textarea
            className="input"
            rows={4}
            value={config.content ?? ""}
            onChange={(event) => set({ content: event.target.value })}
          />
        </Field>
      )}

      {kind === "html" && (
        <Field label="HTML" hint="Rendered in a sandboxed frame.">
          <HtmlLibrary
            html={config.html ?? ""}
            projectId={projectId}
            onLoad={(next) => set({ html: next })}
          />
          <textarea
            className="input font-mono text-xs"
            rows={8}
            value={config.html ?? ""}
            onChange={(event) => set({ html: event.target.value })}
          />
        </Field>
      )}

      {kind === "countdown" && (
        <>
          <Field label="Counting down to">
            <input
              type="datetime-local"
              className="input"
              value={toLocalInput(config.target)}
              onChange={(event) =>
                set({
                  target: event.target.value
                    ? new Date(event.target.value).toISOString()
                    : "",
                })
              }
            />
          </Field>
          <Field label="Caption">
            <input
              className="input"
              value={config.label ?? ""}
              onChange={(event) => set({ label: event.target.value })}
            />
          </Field>
          <Field label="When it runs out">
            <input
              className="input"
              value={config.expired_text ?? ""}
              placeholder="Time is up"
              onChange={(event) => set({ expired_text: event.target.value })}
            />
          </Field>
        </>
      )}

      {kind === "freshness" && (
        <FreshnessFields
          datasets={datasets.data?.items ?? []}
          config={config}
          onChange={set}
        />
      )}
      </Section>

      {/* Only a map has any, and a section with nothing in it is a row that
          asks to be opened and then says nothing. */}
      {kind === "map" && (
      <Section title="Boundaries" summary={summaries.boundaries} open={open.has('bounds')} onToggle={(o) => toggle('bounds', o)}>
        <>
          <Field
            label="Boundaries"
            hint="Enumeration areas, districts or villages, drawn under the pins."
          >
            <select
              className="input"
              aria-label="Boundary layer"
              value={config.boundary_id ?? ""}
              onChange={(event) =>
                // Changing layer drops the two attributes chosen from the old
                // one: they are its column names, and carrying them over would
                // silently check against a property the new layer has not got.
                set({
                  boundary_id: event.target.value || undefined,
                  boundary_key: undefined,
                  boundary_label: undefined,
                })
              }
            >
              <option value="">None</option>
              {boundaries.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.feature_count} areas)
                </option>
              ))}
            </select>
          </Field>

          {config.boundary_id && (
            <>
              <Field
                label="Write on each area"
                hint="Which attribute names it on the map."
              >
                <select
                  className="input"
                  aria-label="Boundary label attribute"
                  value={config.boundary_label ?? ""}
                  onChange={(event) =>
                    set({ boundary_label: event.target.value || undefined })
                  }
                >
                  <option value="">Nothing</option>
                  {boundaryProperties.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </Field>

              <div className="grid gap-x-4 sm:grid-cols-2">
                <Field
                  label="Recorded area"
                  hint="The variable holding the area each record says it was in."
                >
                  <select
                    className="input"
                    aria-label="Recorded area variable"
                    value={config.area_variable ?? ""}
                    onChange={(event) =>
                      set({ area_variable: event.target.value || undefined })
                    }
                  >
                    <option value="">Do not check</option>
                    {(mapDataset.data?.variables ?? [])
                      .filter((v) => !v.is_hidden)
                      .map((v) => (
                        <option key={v.name} value={v.name}>
                          {v.name}
                        </option>
                      ))}
                  </select>
                </Field>
                <Field
                  label="Matched against"
                  hint="The area code on the boundary layer."
                >
                  <select
                    className="input"
                    aria-label="Boundary code attribute"
                    value={config.boundary_key ?? ""}
                    onChange={(event) =>
                      set({ boundary_key: event.target.value || undefined })
                    }
                  >
                    <option value="">Choose…</option>
                    {boundaryProperties.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              {config.area_variable && !config.boundary_key && (
                <p className="mb-4 -mt-2 text-xs text-amber-700">
                  Choose the boundary attribute the recorded area should match,
                  or every record will be reported as a mismatch.
                </p>
              )}
            </>
          )}
        </>
      </Section>
      )}

      <Section title="Appearance" summary={summaries.look} open={open.has('look')} onToggle={(o) => toggle('look', o)}>
      {kind === "map" && (
        <>
          <Field
            label="Point shape"
            hint="A shape is told apart in a photocopy; a shade of a colour is not."
          >
            <select
              className="input"
              aria-label="Map point shape"
              value={config.point_icon ?? "circle"}
              onChange={(event) =>
                set({
                  point_icon:
                    event.target.value === "circle"
                      ? undefined
                      : event.target.value,
                })
              }
            >
              {POINT_ICON_NAMES.map((name) => (
                <option key={name} value={name}>
                  {POINT_ICONS[name].label}
                </option>
              ))}
            </select>
          </Field>

          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="Point colour">
              <ColorPicker
                value={config.point_color ?? ""}
                onChange={(next) => set({ point_color: next || undefined })}
                allowNone
                label="Map point"
                noneLabel="Default blue"
              />
            </Field>
            <Field
              label="Point size"
              hint="How big a pin is before the value scales it."
            >
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={6}
                  max={40}
                  step={1}
                  className="w-40"
                  aria-label="Map point size"
                  value={config.point_size ?? DEFAULT_POINT_SIZE}
                  onChange={(event) =>
                    set({ point_size: Number(event.target.value) })
                  }
                />
                <span className="w-10 text-sm text-ink-600">
                  {config.point_size ?? DEFAULT_POINT_SIZE}
                </span>
              </div>
            </Field>
          </div>

          <Field
            label="Point transparency"
            hint="Low values let a crowd of overlapping pins be read as density rather than one blob."
          >
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={10}
                max={100}
                step={5}
                className="w-40"
                aria-label="Map point transparency"
                value={Math.round(
                  (config.point_opacity ?? DEFAULT_POINT_OPACITY) * 100,
                )}
                onChange={(event) =>
                  set({ point_opacity: Number(event.target.value) / 100 })
                }
              />
              <span className="w-12 text-sm text-ink-600">
                {Math.round(
                  (config.point_opacity ?? DEFAULT_POINT_OPACITY) * 100,
                )}
                %
              </span>
            </div>
          </Field>

          <label className="mb-4 flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={config.size_by_value !== false}
              onChange={(event) => set({ size_by_value: event.target.checked })}
            />
            Bigger pins where the number is bigger
          </label>

          <Field
            label="Base map"
            hint="A reader can switch this on the map itself."
          >
            <select
              className="input"
              value={config.basemap ?? "streets"}
              onChange={(event) =>
                set({
                  basemap:
                    event.target.value === "streets"
                      ? undefined
                      : event.target.value,
                })
              }
            >
              {BASEMAP_NAMES.map((name) => (
                <option key={name} value={name}>
                  {BASEMAPS[name].label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Map tiles" hint="Blank uses the base map above.">
            <input
              className="input font-mono text-xs"
              value={config.tiles ?? ""}
              placeholder={DEFAULT_TILES}
              onChange={(event) => set({ tiles: event.target.value })}
            />
          </Field>
        </>
      )}

      {kind === "chart" && (
        <Field
          label="Chart colour"
          hint="The colour this chart leads with. A chart with several series keeps distinct hues behind it, so they stay tellable apart."
        >
          <ColorPicker
            value={config.series_color ?? ""}
            onChange={(next) => set({ series_color: next || undefined })}
            allowNone
            label="Chart series"
            noneLabel="Use the dashboard's theme"
          />
        </Field>
      )}

      {kind === "chart" && (
        <>
          <label className="mb-3 flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={config.show_values ?? false}
              onChange={(event) => set({ show_values: event.target.checked })}
            />
            Print the value on each bar, slice or point
            <span className="text-ink-400">(up to 24 marks)</span>
          </label>
        </>
      )}

      {/* The same knob for both, because it is the same question: how far away
          is this being read from. On a chart it sets the axes, the legend and
          the printed values; on a data quality panel it sets the findings and
          scales everything else in the panel from them. */}
      {(kind === "chart" || kind === "quality") && (
        <Field
          label={kind === "quality" ? "Text size" : "Chart text size"}
          hint={
            kind === "quality"
              ? "The findings and the lines under them together. Bigger for a board read across a room, smaller for a crowded tile."
              : "The axes, the legend and the printed values together. Bigger for a board read across a room, smaller for a crowded tile."
          }
        >
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={8}
              max={28}
              step={1}
              className="w-40"
              aria-label={kind === "quality" ? "Text size" : "Chart text size"}
              value={config.chart_font_size ?? panelDefault(kind)}
              onChange={(event) =>
                set({ chart_font_size: Number(event.target.value) })
              }
            />
            <span className="w-12 text-sm text-ink-600">
              {config.chart_font_size ?? panelDefault(kind)}px
            </span>
            {config.chart_font_size !== undefined && (
              <button
                className="btn-ghost btn-sm"
                onClick={() => set({ chart_font_size: undefined })}
              >
                Default
              </button>
            )}
          </div>
        </Field>
      )}

      <Field
        label="Background"
        hint="This widget's own colour. The dashboard's transparency still applies to it."
      >
        <ColorPicker
          value={config.background ?? ""}
          onChange={(next) => set({ background: next || undefined })}
          allowNone
          label="Widget background"
          noneLabel="Use the dashboard's colour"
        />
      </Field>

      <Field
        label="Transparency"
        hint="How much of the dashboard's background shows through this widget. Empty follows the dashboard."
      >
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={30}
            max={100}
            step={5}
            className="w-48"
            aria-label="Widget transparency"
            value={Math.round((config.opacity ?? dashboardOpacity) * 100)}
            onChange={(event) =>
              set({ opacity: Number(event.target.value) / 100 })
            }
          />
          <span className="w-12 text-sm text-ink-600">
            {Math.round((config.opacity ?? dashboardOpacity) * 100)}%
          </span>
          {config.opacity !== undefined && (
            <button
              className="btn-ghost btn-sm"
              onClick={() => set({ opacity: undefined })}
            >
              Follow dashboard
            </button>
          )}
        </div>
      </Field>

      <Field label="Font">
        <select
          className="input"
          aria-label="Widget font"
          value={config.font_family ?? ""}
          onChange={(event) =>
            set({ font_family: event.target.value || undefined })
          }
          style={config.font_family ? { fontFamily: config.font_family } : undefined}
        >
          {FONTS.map((font) => (
            <option
              key={font.id}
              value={font.stack}
              style={font.stack ? { fontFamily: font.stack } : undefined}
            >
              {font.label} - {font.note}
            </option>
          ))}
          {/* A stack from before the catalogue, or one set by hand. It renders
              perfectly well, so the picker shows it as the current choice
              instead of snapping back to the interface font and losing it. */}
          {config.font_family && !fontFor(config.font_family) && (
            <option value={config.font_family}>Current (set earlier)</option>
          )}
        </select>
      </Field>

      <Field
        label="Text colour"
        hint="The title, the caption, and the labels on the chart: its axes, its legend and the values beside its marks."
      >
        <ColorPicker
          value={config.font_color ?? ""}
          onChange={(next) => set({ font_color: next || undefined })}
          allowNone
          label="Widget text"
          noneLabel="Default text colour"
        />
      </Field>

      <Field label="Title font">
        <select
          className="input"
          aria-label="Widget title font"
          value={config.title_font ?? ""}
          onChange={(event) =>
            set({ title_font: event.target.value || undefined })
          }
        >
          {FONTS.map((font) => (
            <option
              key={font.id}
              value={font.id}
              style={font.stack ? { fontFamily: font.stack } : undefined}
            >
              {font.label}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Title position">
        <select
          className="input"
          aria-label="Widget title position"
          value={config.title_align ?? "left"}
          onChange={(event) =>
            set({
              title_align:
                event.target.value === "left"
                  ? undefined
                  : (event.target.value as "center" | "right"),
            })
          }
        >
          <option value="left">Left</option>
          <option value="center">Centred</option>
          <option value="right">Right</option>
        </select>
      </Field>

      <Field
        label="Shadow"
        hint="Lifts this widget off the dashboard behind it."
      >
        <select
          className="input"
          aria-label="Widget shadow"
          value={config.shadow ?? "none"}
          onChange={(event) =>
            set({
              shadow:
                event.target.value === "none"
                  ? undefined
                  : (event.target.value as "soft" | "strong"),
            })
          }
        >
          <option value="none">None</option>
          <option value="soft">Soft</option>
          <option value="strong">Strong</option>
        </select>
      </Field>

      <Field label="Title size" hint="Empty follows the rest of the widget.">
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={11}
            max={32}
            step={1}
            className="w-48"
            aria-label="Widget title size"
            value={config.title_size ?? DEFAULT_TITLE_SIZE}
            onChange={(event) =>
              set({ title_size: Number(event.target.value) })
            }
          />
          <span className="w-12 text-sm text-ink-600">
            {config.title_size ?? DEFAULT_TITLE_SIZE}px
          </span>
          {config.title_size !== undefined && (
            <button
              className="btn-ghost btn-sm"
              onClick={() => set({ title_size: undefined })}
            >
              Default
            </button>
          )}
        </div>
      </Field>
      </Section>

    </Modal>
  );
}

/** An ISO instant as the value a datetime-local input wants. */
export function toLocalInput(iso: unknown): string {
  if (!iso || typeof iso !== "string") return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}T${pad(
    when.getHours(),
  )}:${pad(when.getMinutes())}`;
}

/** Which datasets the freshness widget watches, and when to call them stale. */
export function FreshnessFields({
  datasets,
  config,
  onChange,
}: {
  datasets: Dataset[];
  config: Record<string, any>;
  onChange: (patch: Record<string, any>) => void;
}) {
  const chosen: string[] = config.dataset_ids ?? [];
  const toggle = (id: string) =>
    onChange({
      dataset_ids: chosen.includes(id)
        ? chosen.filter((existing) => existing !== id)
        : [...chosen, id],
    });

  return (
    <>
      <Field
        label="Datasets to watch"
        hint="Each gets a line saying how recent it is."
      >
        <div className="grid max-h-52 gap-1 overflow-auto sm:grid-cols-2">
          {datasets.map((dataset) => (
            <label
              key={dataset.id}
              className="flex items-center gap-2 text-sm text-ink-700"
            >
              <input
                type="checkbox"
                checked={chosen.includes(dataset.id)}
                onChange={() => toggle(dataset.id)}
              />
              <span className="truncate">{dataset.name}</span>
            </label>
          ))}
        </div>
      </Field>
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="Amber after (hours)">
          <input
            className="input"
            type="number"
            min={1}
            value={config.warn_hours ?? 24}
            onChange={(event) =>
              onChange({ warn_hours: Number(event.target.value) || 24 })
            }
          />
        </Field>
        <Field label="Red after (hours)">
          <input
            className="input"
            type="number"
            min={1}
            value={config.critical_hours ?? 72}
            onChange={(event) =>
              onChange({ critical_hours: Number(event.target.value) || 72 })
            }
          />
        </Field>
      </div>
    </>
  );
}
