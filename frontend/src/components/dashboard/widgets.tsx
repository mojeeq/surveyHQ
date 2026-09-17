import { useQuery } from "@tanstack/react-query";

import { useEffect, useState } from "react";

import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

import { api } from "@/lib/api";


import { STATUS_COLORS } from "@/lib/charts";

import type { BuildOptions } from "@/lib/charts";

import { formatNumber, formatValue, relativeTime } from "@/lib/format";

import {
  CHECK_COLOURS,
  checkState,
  countResult,
  qualityChartType,
  rateResult,
  trendResult,
  worstFirst,
} from "@/lib/quality";

import type { Widget } from "@/lib/types";

import ChartCard from "@/components/ChartCard";

import MapWidget, { type BoundaryOverlay } from "@/components/MapWidget";

import { DEFAULT_PANEL_TEXT } from "@/components/dashboard/shared";
import { Badge } from "@/components/ui";

/**
 * Time left until a deadline, ticking.
 *
 * Fieldwork is run against dates - the day enumeration closes, the day the
 * report is due - and a board that reports progress is read against how much
 * of that time is left. The number is computed in the browser rather than sent
 * by the server, so it goes on counting down on a screen nobody is touching.
 */
/**
 * Whatever markup the dashboard's author pasted in.
 *
 * It runs in a sandboxed frame with no same-origin privilege, so scripts in it
 * execute in an opaque origin: they cannot read this page, its storage or its
 * session, which is what makes accepting arbitrary markup from one user and
 * showing it to another safe to do at all. That is also why it is a frame
 * rather than dangerouslySetInnerHTML, which would run it right here.
 */
/**
 * A map, with its boundary outlines fetched separately from its pins.
 *
 * Two requests rather than one on purpose. The pins change with every filter
 * and every refresh; the outlines are a national frame that changes when
 * somebody uploads a new one, which is to say almost never. Sending the frame
 * down with each refresh of the pins would be megabytes an hour to redraw
 * something identical.
 *
 * It goes through the dashboard's own path so a shared link draws its outlines
 * too - the reader of a shared board has no account to check.
 */
export function BoundedMap({
  payload,
  widget,
  basePath,
}: {
  payload: any;
  widget: Widget;
  basePath: string;
}) {
  const boundary = payload.boundary as BoundaryOverlay | undefined;
  const areas = useQuery({
    queryKey: ["dashboard-boundary", basePath, boundary?.id],
    queryFn: () =>
      api.get<{ type: string; features: never[] }>(
        `${basePath}/boundaries/${boundary!.id}`,
      ),
    enabled: Boolean(boundary?.id),
    // The frame does not move. Refetching it on every window focus would be
    // the one thing on this page reliably wasting the field office's bandwidth.
    staleTime: 60 * 60 * 1000,
  });

  return (
    <MapWidget
      points={payload.points ?? []}
      detail={payload.detail ?? []}
      measure={payload.measure}
      basemap={widget.config?.basemap as string | undefined}
      icon={widget.config?.point_icon as string | undefined}
      pointColor={widget.config?.point_color as string | undefined}
      pointSize={widget.config?.point_size as number | undefined}
      pointOpacity={widget.config?.point_opacity as number | undefined}
      sizeByValue={widget.config?.size_by_value !== false}
      tiles={widget.config?.tiles as string | undefined}
      truncated={payload.truncated}
      boundary={boundary}
      areas={areas.data}
      areaVariable={payload.area_check?.variable}
    />
  );
}

export function HtmlWidget({ html }: { html: string }) {
  if (!html.trim()) {
    return (
      <p className="py-6 text-center text-sm text-ink-400">
        This embed is empty
      </p>
    );
  }
  return (
    <iframe
      title="Embedded content"
      srcDoc={html}
      sandbox="allow-scripts allow-popups allow-forms"
      referrerPolicy="no-referrer"
      className="h-full min-h-[120px] w-full border-0"
    />
  );
}

/**
 * How recent the data is, which is two questions.
 *
 * When the platform last received data says whether the import is running.
 * When the newest record in it was collected says whether the field teams are
 * still sending anything - and an import that runs faithfully every morning
 * and collects nothing new is healthy by the first measure and broken by the
 * second, which is the failure this widget exists to catch.
 */
export function FreshnessWidget({ payload }: { payload: any }) {
  const lines: any[] = payload.datasets ?? [];
  return (
    <div className="flex h-full flex-col gap-2 overflow-auto">
      {lines.map((line) => {
        const colour =
          STATUS_COLORS[line.status as keyof typeof STATUS_COLORS] ??
          STATUS_COLORS.unknown;
        return (
          <div key={line.dataset_id} className="flex items-start gap-2.5">
            <span
              className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: colour }}
              // The dot is colour; the words beside it carry the same meaning,
              // so it is never the only thing saying whether this is stale.
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink-800">
                {line.name}
              </p>
              <p className="text-xs text-ink-500">
                Imported {relativeTime(line.imported_at)}
                {line.latest_record_at ? (
                  <>
                    {" · newest record "}
                    {relativeTime(line.latest_record_at)}
                  </>
                ) : line.date_variable ? null : (
                  <span className="text-ink-400">
                    {" "}
                    · no date column to read
                  </span>
                )}
              </p>
              {line.error && (
                <p className="text-xs text-amber-700">{line.error}</p>
              )}
            </div>
            <span className="shrink-0 text-xs tabular-nums text-ink-400">
              {formatNumber(line.rows)} rows
            </span>
          </div>
        );
      })}
      {!lines.length && (
        <p className="py-6 text-center text-sm text-ink-400">
          Nothing to report
        </p>
      )}
    </div>
  );
}

export function CountdownWidget({ payload }: { payload: any }) {
  const target = payload.target ? new Date(payload.target).getTime() : NaN;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!Number.isFinite(target)) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [target]);

  if (!Number.isFinite(target)) {
    return (
      <p className="py-6 text-center text-sm text-ink-400">
        No date set for this countdown
      </p>
    );
  }

  const remaining = target - now;
  if (remaining <= 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
        <p className="text-2xl font-semibold text-red-600">
          {payload.expired_text || "Time is up"}
        </p>
        <p className="text-xs text-ink-500">
          {payload.label || new Date(target).toLocaleString()}
        </p>
      </div>
    );
  }

  const seconds = Math.floor(remaining / 1000);
  const parts = [
    { value: Math.floor(seconds / 86400), unit: "days" },
    { value: Math.floor((seconds % 86400) / 3600), unit: "hours" },
    { value: Math.floor((seconds % 3600) / 60), unit: "min" },
    { value: seconds % 60, unit: "sec" },
  ];

  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
      <div className="flex items-end gap-3">
        {parts.map((part) => (
          <div key={part.unit}>
            <div className="text-3xl font-semibold tabular-nums text-ink-900">
              {String(part.value).padStart(2, "0")}
            </div>
            <div className="text-[11px] uppercase tracking-wide text-ink-400">
              {part.unit}
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-ink-500">
        {payload.label || `until ${new Date(target).toLocaleString()}`}
      </p>
    </div>
  );
}


export function QualityWidget({
  payload,
  view,
  chart,
  theme,
  display,
}: {
  payload: any;
  /** Which of the panel's forms this widget was saved showing. */
  view: string;
  /** How that form is drawn, where the form is a chart. */
  chart?: string;
  theme: string;
  display?: BuildOptions;
}) {
  const failing = payload.checks.filter((c: any) => c.passed === false);
  const stale = payload.oldest_run_at;
  const charted = view === "rate" || view === "rows" || view === "trend";
  const chartType = qualityChartType(view, chart);
  // A horizontal bar's categories read bottom-up, so the worst check goes last
  // in the data; every other form reads from the top left and wants it first.
  const horizontal = chartType === "horizontal_bar";
  // Colouring a mark by its finding is for the bars only. A table has no marks,
  // and a pie is read for how the flagged rows divide between the checks: paint
  // its slices by state and every failing check comes out the same red, which
  // leaves the legend as the only thing telling one slice from the next.
  const marked = chartType === "horizontal_bar" || chartType === "bar";
  return (
    // One size for the whole panel, and every part of it sized in em from
    // there: a finding is read at a glance from wherever the board is, and
    // what "big enough" means depends on whether that is a desk or a wall.
    // The widget's own text size sets it where one was chosen.
    <div
      className="flex h-full flex-col [&_.chip]:text-[0.8em]"
      style={{ fontSize: `${display?.fontSize ?? DEFAULT_PANEL_TEXT}px` }}
    >
      {/* No "N failing" count. The list underneath is the failing checks,
          named and numbered, so the badge was a label for something already on
          the screen - and a red pill at the top of every quality panel made a
          board of them read as an emergency. What is left says what the list
          cannot: how many checks passed, and how many have never run.

          Except on a chart, where there is no list to be redundant with. The
          trend view draws history in the categorical palette and names no
          state at all, so without this a panel of failing checks looks exactly
          like a panel of passing ones. It reads as a count beside the others
          rather than as an alarm.

          The row goes entirely when it has nothing to say, rather than sitting
          there as an empty strip with a margin under it. */}
      {(charted && payload.failing > 0) ||
      payload.passing > 0 ||
      payload.never_run > 0 ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {charted && payload.failing > 0 && (
            <Badge tone="neutral">{payload.failing} failing</Badge>
          )}
          {payload.passing > 0 && (
            <Badge tone="neutral">{payload.passing} passing</Badge>
          )}
          {payload.never_run > 0 && (
            <Badge tone="warning">{payload.never_run} never run</Badge>
          )}
        </div>
      ) : null}

      {!payload.checks.length ? (
        <p className="text-ink-500">No active checks on {payload.name}.</p>
      ) : charted ? (
        // A table drawn here is the panel's data like any other form of it, so
        // it takes the panel's text size. Nothing else in the widget has to
        // ask: the size is set on the panel and everything under it is in em.
        // A table is not - `.table-base` pins 13px and its headings 12px, for
        // the tables on every other page, where there is no such setting - so
        // the two rules are put back in em from here. Reaching in by class is
        // the cheap half of the alternative, which is a size prop threaded
        // through ChartCard into a component that has never needed one.
        <div
          className={`min-h-0 flex-1 ${
            chartType === "table"
              ? "[&_.table-base]:text-[1em] [&_.table-base_thead_th]:text-[0.8em]"
              : ""
          }`}
        >
          {view === "trend" && !payload.history ? (
            <p className="text-ink-500">
              No runs stored yet. The checks run every few hours, and a line
              needs two days of them.
            </p>
          ) : (
            <ChartCard
              fill
              showToggle={false}
              theme={theme}
              chartType={chartType}
              result={
                view === "trend"
                  ? trendResult(payload.history)
                  : view === "rows"
                    ? countResult(payload.checks, horizontal)
                    : rateResult(payload.checks, horizontal)
              }
              display={{
                ...display,
                showValues: display?.showValues ?? view !== "trend",
                sort: "none",
                decimals: view === "rows" ? 0 : 2,
                // Colour is the finding here. A bar's hue says whether that
                // check is passing, which is the thing being looked for, so it
                // is not left to the palette's order.
                ...(view === "trend"
                  ? // No axis title: the legend needs the top of the plot, the
                    // footnote below says what the numbers are, and the two
                    // were landing on each other at widget width.
                    { showLegend: true, smooth: false }
                  : marked
                    ? {
                        pointColors: worstFirst(
                          payload.checks,
                          (check: any) =>
                            view === "rows"
                              ? (check.failed_rows ?? 0)
                              : (check.failure_rate ?? 0),
                          horizontal,
                        ).map((check: any) => CHECK_COLOURS[checkState(check)]),
                      }
                    : {}),
              }}
            />
          )}
        </div>
      ) : (
        <ul className="min-h-0 flex-1 space-y-2 overflow-auto">
          {failing.map((check: any) => (
            <li
              key={check.id}
              className="aero-pane border-ink-200 bg-white px-3 py-2 dark:border-dark-300 dark:bg-dark-100"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 font-medium text-ink-900 dark:text-dark-900">
                  {check.name}
                </p>
                {/* The number the check turns on, where the eye lands after
                    the name. It is what a supervisor acts on, and reading it
                    out of the middle of a sentence is slower than reading it
                    off the right-hand edge of every box in the column. */}
                {check.failure_rate > 0 && (
                  <span className="chip shrink-0 border-ink-200 bg-ink-100 tabular-nums text-ink-700 dark:border-dark-300 dark:bg-dark-200 dark:text-dark-700">
                    {(check.failure_rate * 100).toFixed(
                      check.failure_rate < 0.01 ? 2 : 0,
                    )}
                    %
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-[0.87em] text-ink-600 dark:text-dark-700">
                {check.message}
              </p>
              {payload.filtered && check.total_rows > 0 && (
                <p className="mt-0.5 text-[0.8em] text-ink-500 dark:text-dark-600">
                  {formatNumber(check.failed_rows)} of{" "}
                  {formatNumber(check.total_rows)} rows in view
                </p>
              )}
            </li>
          ))}
          {!failing.length && (
            <li className="aero-pane aero-pane-ok px-3 py-2 pl-4 text-emerald-600">
              <p className="font-medium text-emerald-900 dark:text-emerald-200">
                Every active check passed
              </p>
              <p className="mt-0.5 text-[0.87em] text-emerald-800/90 dark:text-emerald-200/80">
                {payload.name}
              </p>
            </li>
          )}
        </ul>
      )}

      {view === "trend" ? (
        <p className="mt-2 text-[0.8em] text-ink-400">
          {/* The line is drawn from what the scheduled runs stored, and those
              counted the whole dataset. A filter cannot reach backwards into
              them, and a line that quietly ignored the page's filter while the
              widgets around it obeyed it would be read as agreeing with them. */}
          The last run of each day, over the whole dataset
          {payload.filtered ? ". The filters on this page do not reach it" : ""}
        </p>
      ) : payload.filtered ? (
        <p className="mt-2 text-[0.8em] text-ink-400">
          {/* Counted against the page's filter just now, so there is no "last
              run" to date it by - and saying which it is matters, because the
              two answer different questions about the same rule. */}
          Counted for the filters on this page
        </p>
      ) : (
        stale && (
          <p className="mt-2 text-[0.8em] text-ink-400">
            {/* Results are shown as last run, not recomputed on open, so say when. */}
            Oldest result {relativeTime(stale)}
          </p>
        )
      )}
    </div>
  );
}

/** The recent history of one number, drawn small enough to sit in a tile.
 *
 *  Inline SVG rather than a chart: a sparkline has no axes, no legend and no
 *  tooltip, and building a whole chart to draw one polyline in a 40px strip
 *  costs more than it draws. The shape is the message.
 */
export function Sparkline({
  points,
  color,
  height = 32,
}: {
  points: { at: string; value: number | null }[];
  color: string;
  height?: number;
}) {
  const values = points
    .map((point) => point.value)
    .filter(
      (value): value is number => value !== null && Number.isFinite(value),
    );
  if (values.length < 2) return null;

  const low = Math.min(...values);
  const high = Math.max(...values);
  // A flat line has no range to scale by, and dividing by it would put every
  // point at the top of the box. Drawn down the middle instead, which is what
  // a number that has not moved looks like.
  const span = high - low || 1;
  const width = 100;
  const path = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - low) / span) * (height - 4) - 2;
      return `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const last = values[values.length - 1];
  const lastX = width;
  const lastY = height - ((last - low) / span) * (height - 4) - 2;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="mt-2 h-8 w-full shrink-0"
      role="img"
      aria-label={`Trend over the last ${values.length} runs`}
    >
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
      {/* Where it has got to, so the eye lands on the current value rather
          than wandering the line looking for the end of it. */}
      <circle
        cx={lastX}
        cy={lastY}
        r="2"
        fill={color}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** How far off target, said in words rather than left as a subtraction.
 *
 *  No coloured circle: the wording and the tint carry it, and a status dot
 *  beside a number that already says "63 behind" is decoration.
 */
export function Variance({
  variance,
  percent,
  format,
  unit,
  lowerIsBetter,
}: {
  variance: number;
  percent: number | null | undefined;
  format: string;
  unit: string;
  lowerIsBetter: boolean;
}) {
  // Over target is good news when higher is better and bad news when it is a
  // ceiling, so which way is "good" is the indicator's to say, not the sign's.
  const good = lowerIsBetter ? variance <= 0 : variance >= 0;
  const over = variance >= 0;
  const word = lowerIsBetter
    ? over
      ? "over the limit"
      : "under the limit"
    : over
      ? "ahead of target"
      : "behind target";
  return (
    <p
      className={`mt-1 text-sm font-medium ${
        good
          ? "text-emerald-700 dark:text-emerald-400"
          : "text-rose-700 dark:text-rose-400"
      }`}
    >
      {over ? "+" : "-"}
      {formatValue(Math.abs(variance), format, unit)} {word}
      {percent !== null && percent !== undefined && (
        <span className="ml-1 font-normal opacity-70">
          ({over ? "+" : "-"}
          {Math.abs(percent).toFixed(percent >= 10 || percent <= -10 ? 0 : 1)}%)
        </span>
      )}
    </p>
  );
}

export function IndicatorWidget({
  payload,
  theme,
  display,
  onSelect,
}: {
  payload: any;
  theme: string;
  /** The tile's own font, ink and text size, for the chart under the number. */
  display?: BuildOptions;
  /** Filter the page by a category of this indicator's breakdown. */
  onSelect?: (variable: string, value: string) => void;
}) {
  const color =
    STATUS_COLORS[payload.status as keyof typeof STATUS_COLORS] ??
    STATUS_COLORS.unknown;
  const breakdown: Record<string, number> = payload.breakdown ?? {};
  const groups = Object.entries(breakdown);

  /**
   * Each group's progress towards its own quota, drawn as one bar.
   *
   * Stacking the actual on top of the target would be arithmetic nonsense -
   * 86 interviews plus a quota of 100 is not 186 of anything. What a quota
   * chart has to show is how much of the target is done and how much is left,
   * so the bar IS the target, split into what has been achieved and what is
   * still to go. Read across, the coloured part is the actual and the whole
   * bar is the quota, which is the comparison being asked for.
   *
   * Overshoot gets its own segment rather than being clipped: a region at 120
   * of 100 must not look identical to one that has landed exactly on its quota.
   *
   * Only when some group actually has a target. An indicator broken down for
   * interest would otherwise grow a "still to go" segment of nothing.
   */
  const progress: Record<
    string,
    {
      value: number;
      target: number | null;
      percent: number | null;
      status: string;
    }
  > = payload.breakdown_progress ?? {};
  const hasTargets = groups.some(
    ([key]) => (progress[key]?.target ?? null) !== null,
  );

  // "Lower is better" reads the other way round. A rejection rate with a
  // target of 5% is a ceiling, not something to work towards: the space under
  // it is headroom nobody is trying to fill, so there is no "still to go" -
  // only whether the limit has been passed, which is bad rather than good.
  const lowerIsBetter = payload.direction === "lower_is_better";

  /** The stored runs behind the number, for the line under it. Empty unless
   *  the widget asked, and never beside a filtered value: those runs counted
   *  the whole dataset and the number above them does not. */
  const trend: { at: string; value: number | null }[] = payload.trend ?? [];

  const overLabel = lowerIsBetter ? "Over the limit" : "Over target";
  const achievedLabel = lowerIsBetter ? "Within the limit" : "Achieved";
  // Two segments when lower is better, three otherwise. Carrying a "still to
  // go" of zero would put a series in the legend that can never be drawn.
  const quotaSeries = lowerIsBetter
    ? [achievedLabel, overLabel]
    : [achievedLabel, "Still to go", overLabel];

  const quotaRows = groups.map(([key, value]) => {
    const target = progress[key]?.target ?? null;
    const within = target === null ? value : Math.min(value, target);
    const over = target === null ? 0 : Math.max(value - target, 0);
    const left = target === null ? 0 : Math.max(target - value, 0);
    return lowerIsBetter ? [key, within, over] : [key, within, left, over];
  });

  return (
    <div
      className={`flex h-full flex-col ${groups.length ? "" : "justify-center"}`}
    >
      <p className="text-3xl font-semibold tabular-nums text-ink-900">
        {formatValue(payload.value, payload.value_format, payload.unit)}
      </p>
      {/* The number on its own answers nothing. How far off target it is, and
          which way it has been moving, are what the tile is on the wall for. */}
      {typeof payload.variance === "number" && (
        <Variance
          variance={payload.variance}
          percent={payload.variance_percent}
          format={payload.value_format}
          unit={payload.unit}
          lowerIsBetter={lowerIsBetter}
        />
      )}
      {/* Neutral on purpose. The status colour beside a variance that says
          the opposite - a green line under "283 behind target" - reads as a
          contradiction, and the shape of the line is the message anyway. */}
      {trend.length > 1 && <Sparkline points={trend} color="#94a3b8" />}
      {payload.target_value !== null && payload.target_value !== undefined && (
        <>
          {/* shrink-0: this sits in a column flex container, which would otherwise
              compress the track to zero height in a short widget. */}
          <div className="mt-3 h-2 shrink-0 overflow-hidden rounded-full bg-ink-100">
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.min(payload.progress_percent ?? 0, 100)}%`,
                backgroundColor: color,
              }}
            />
          </div>
          <p className="mt-1.5 text-xs text-ink-500">
            {payload.progress_percent?.toFixed(0) ?? "-"}% of{" "}
            {formatNumber(payload.target_value)}
          </p>
        </>
      )}
      {payload.filtered ? (
        /* Computed against the page's filter just now, so there is no "last
           run" to date it by. Saying which it is matters: a tile that reports
           the whole survey while the page is narrowed to one province is
           answering a question nobody asked. */
        <p className="mt-2 text-[11px] text-ink-400">
          Counted for the filters on this page
        </p>
      ) : (
        payload.computed_at && (
          <p className="mt-2 text-[11px] text-ink-400">
            Updated {relativeTime(payload.computed_at)}
          </p>
        )
      )}

      {/* The headline is an average of something. Which regions or teams are
          behind it is the next question, and it used to need another page. */}
      {groups.length > 0 && (
        <div className="mt-3 min-h-0 flex-1">
          <ChartCard
            showToggle={false}
            chartType="horizontal_bar"
            fill
            theme={theme}
            result={{
              columns: hasTargets
                ? [
                    {
                      name: "group",
                      label: payload.breakdown_variable || "Group",
                      type: "dimension",
                      data_type: "text",
                    },
                    ...quotaSeries.map((label) => ({
                      name: label,
                      label,
                      type: "measure" as const,
                      data_type: "number" as const,
                    })),
                  ]
                : [
                    {
                      name: "group",
                      label: payload.breakdown_variable || "Group",
                      type: "dimension",
                      data_type: "text",
                    },
                    {
                      name: "value",
                      label: payload.name ?? "Value",
                      type: "measure",
                      data_type: "number",
                    },
                  ],
              rows: hasTargets
                ? quotaRows
                : groups.map(([key, value]) => [key, value]),
              row_count: groups.length,
              truncated: false,
              sql: "",
              duration_ms: 0,
            }}
            display={{
              ...display,
              // Numbers on the marks only without targets. On the stacked form
              // they would be printed on each segment, including the empty
              // ones, and three labels across a short bar is a smear.
              showValues: !hasTargets,
              stacked: hasTargets,
              showLegend: hasTargets,
              // "Still to go" is an absence rather than a category, so it
              // takes a neutral instead of a hue competing with the value
              // beside it. Overshoot is not given a colour that asserts good
              // or bad on its own: passing the target is good news for "higher
              // is better" and bad news for "lower is better", so where it is
              // bad it takes the warning tone and otherwise a paler tint of
              // the achieved colour - more of the same thing, not a new one.
              seriesColors: hasTargets
                ? lowerIsBetter
                  ? ["", STATUS_COLORS.critical]
                  : ["", "#e1e0d9", "#9ec5f4"]
                : undefined,
            }}
            // An indicator's breakdown is a chart of a variable like any other,
            // so clicking a bar filters the page by it. It used to be the one
            // chart on a dashboard that did nothing when clicked.
            onSelect={
              onSelect && payload.breakdown_variable
                ? (category) => onSelect(payload.breakdown_variable, category)
                : undefined
            }
          />
        </div>
      )}
    </div>
  );
}
