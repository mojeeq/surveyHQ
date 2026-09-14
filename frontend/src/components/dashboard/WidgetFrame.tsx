import { useEffect, useRef, useState, type CSSProperties } from "react";

import { createPortal } from "react-dom";

import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

import { copyableIn, copyChart, copyTable } from "@/lib/clipboard";

import { useToast } from "@/hooks/useToast";

import type { Widget } from "@/lib/types";

import ChartCard from "@/components/ChartCard";

import CrosstabTable from "@/components/CrosstabTable";

import { clickedVariable } from "@/components/dashboard/filters";
import {
  styleOf,
  titleStyle,
  widgetInk,
  widgetTone,
} from "@/components/dashboard/shared";
import {
  BoundedMap,
  CountdownWidget,
  FreshnessWidget,
  HtmlWidget,
  IndicatorWidget,
  QualityWidget,
} from "@/components/dashboard/widgets";
import { Loading } from "@/components/ui";

/** One line on a widget's menu. */
import { WidgetMenu } from "./WidgetMenu";

export function WidgetFrame({
  widget,
  payload,
  loading,
  editing,
  card,
  ground,
  canEdit,
  theme,
  pageNames,
  basePath,
  onMove,
  onEdit,
  onRemove,
  onSelect,
  drilledTo,
  openComments,
  onComment,
}: {
  widget: Widget;
  payload: any;
  loading: boolean;
  editing: boolean;
  canEdit: boolean;
  /** The tile's own colour, so the expanded view is the same widget. */
  card?: CSSProperties;
  /** What the dashboard lays behind its widgets, under a see-through one. */
  ground?: CSSProperties;
  /** Where this dashboard's own resources live, shared or signed in. */
  basePath: string;
  /** The dashboard's categorical ordering, applied to every chart on it. */
  theme: string;
  /** Every page on this dashboard, so a widget can be sent to another one. */
  pageNames: string[];
  onMove: (page: number) => void;
  onEdit: () => void;
  onRemove: () => void;
  /** A mark was clicked: filter the rest of the page by what it stands for. */
  onSelect?: (variable: string, value: string) => void;
  /** The level this widget is drawn at, when the board has drilled past the
   *  one its title names. "Interviews by province" showing districts is not
   *  wrong, but it does need to say so. */
  drilledTo?: string;
  /** Threads on this widget nobody has marked dealt with, for the count. */
  openComments?: number;
  /** Open the conversation about this widget. Absent on a shared link, which
   *  has no reader to attribute a comment to. */
  onComment?: () => void;
}) {
  const style = styleOf(widget);
  const body = useRef<HTMLDivElement>(null);
  const toast = useToast();
  const [expanded, setExpanded] = useState(false);
  const name = widget.title || payload?.name || "Widget";

  // What this widget can be handed over as, judged from what it actually drew
  // rather than from its type: a chart shown as a table is a table to copy.
  const [copyable, setCopyable] = useState<"table" | "chart" | null>(null);
  useEffect(() => {
    setCopyable(copyableIn(body.current));
  }, [payload, expanded]);

  const handOver = async () => {
    const node = body.current;
    if (!node) return;
    try {
      const table = node.querySelector("table");
      if (table) {
        toast.push(await copyTable(table as HTMLTableElement), "success");
        return;
      }
      const canvas = node.querySelector("canvas");
      if (canvas)
        toast.push(
          await copyChart(canvas as HTMLCanvasElement, name),
          "success",
        );
    } catch (error) {
      toast.push((error as Error).message, "error");
    }
  };

  // The widget itself, so the same thing can be drawn in the tile and, at
  // the size of the window, in the overlay below. Written once because the
  // two must not drift: an expanded widget showing something subtly
  // different from the tile it came from would be worse than no overlay.
  const content = loading ? (
    <Loading />
  ) : !payload ? (
    <p className="py-6 text-center text-sm text-ink-400">No data</p>
  ) : payload.error ? (
    <p className="aero-pane aero-pane-warn px-3 py-2 pl-4 text-xs text-amber-900 dark:text-amber-200">
      {payload.error}
    </p>
  ) : payload.type === "indicator" ? (
    <IndicatorWidget
      payload={payload}
      theme={theme}
      onSelect={onSelect}
      // The tile's own styling, the same way every other widget gets it.
      // Without this the breakdown chart under the number kept the default
      // near-black axis labels on a tile somebody had painted slate.
      display={{
        ...(style.font_family ? { fontFamily: style.font_family } : {}),
        ...(widgetInk(style) ? { fontColor: widgetInk(style) } : {}),
        ...(style.chart_font_size ? { fontSize: style.chart_font_size } : {}),
      }}
    />
  ) : payload.type === "quality" ? (
    <QualityWidget
      payload={payload}
      view={String((widget.config as any)?.quality_view || "list")}
      theme={theme}
      display={{
        ...(style.series_color ? { seriesColor: style.series_color } : {}),
        ...(style.font_family ? { fontFamily: style.font_family } : {}),
        ...(widgetInk(style) ? { fontColor: widgetInk(style) } : {}),
        ...(style.chart_font_size ? { fontSize: style.chart_font_size } : {}),
        ...(style.show_values === undefined
          ? {}
          : { showValues: style.show_values }),
      }}
    />
  ) : payload.type === "crosstab" ? (
    <CrosstabTable
      result={payload.result}
      compact
      fill
      // A cross-tab carries both its variables in the result, so it can
      // say which one a heading belongs to without the server naming it.
      onSelect={onSelect}
    />
  ) : payload.type === "freshness" ? (
    <FreshnessWidget payload={payload} />
  ) : payload.type === "map" ? (
    <BoundedMap payload={payload} widget={widget} basePath={basePath} />
  ) : payload.type === "html" ? (
    <HtmlWidget html={payload.html ?? ""} />
  ) : payload.type === "countdown" ? (
    <CountdownWidget payload={payload} />
  ) : payload.type === "text" ? (
    <p className="whitespace-pre-wrap text-sm text-ink-700">
      {payload.content}
    </p>
  ) : payload.result ? (
    <ChartCard
      result={payload.result}
      chartType={payload.chart_type ?? "bar"}
      fill
      showToggle={false}
      theme={theme}
      display={{
        ...payload.display,
        // The widget's own styling wins over what the chart was saved
        // with: it is set here, on this dashboard, for this tile.
        ...(style.series_color ? { seriesColor: style.series_color } : {}),
        ...(style.font_family ? { fontFamily: style.font_family } : {}),
        ...(widgetInk(style) ? { fontColor: widgetInk(style) } : {}),
        ...(style.chart_font_size ? { fontSize: style.chart_font_size } : {}),
        // Undefined leaves whatever the chart was saved with; false is a
        // decision to turn the numbers off, and has to survive the spread.
        ...(style.show_values === undefined
          ? {}
          : { showValues: style.show_values }),
      }}
      onSelect={
        // Only where a click means something: a chart grouped on a
        // variable. A KPI or a table of measures has no category behind
        // the mark, so clicking it would filter by nothing.
        onSelect && clickedVariable(payload)
          ? (category) => onSelect(clickedVariable(payload), category)
          : undefined
      }
    />
  ) : null;

  return (
    // The hover group is the whole widget, not just its title bar. It used to
    // be the bar alone, which meant the edit and remove controls stayed
    // invisible until the pointer found a strip about forty pixels tall: you
    // moved towards the widget, saw no button, clicked, and hit the chart -
    // which cross-filters the page. It read as "editing takes a few clicks".
    // Approaching the widget at all is enough intent to show its controls.
    <div className="group flex h-full flex-col">
      <header className="widget-handle flex shrink-0 items-center justify-between gap-2 border-b border-ink-200 px-4 py-2.5">
        <h3
          className={`min-w-0 truncate text-sm font-semibold text-ink-800 ${
            editing ? "cursor-move" : ""
          } ${
            // grow so the alignment has room to act in: a title sized to its
            // own text is already centred inside itself and centring it again
            // does nothing visible.
            style.title_align === "center"
              ? "flex-1 text-center"
              : style.title_align === "right"
                ? "flex-1 text-right"
                : ""
          }`}
          style={titleStyle(style)}
        >
          {widget.title || payload?.name || "Widget"}
          {drilledTo && (
            <span className="ml-1.5 font-normal text-ink-500">
              - by {drilledTo}
            </span>
          )}
        </h3>
        {/* How many questions are open on this widget. A count on the header
            rather than an icon on every tile: a widget nobody has said
            anything about should look exactly as it did before. */}
        {onComment && Boolean(openComments) && (
          <button
            className="shrink-0 rounded bg-brand-50 px-1.5 py-0.5 text-xs font-medium text-brand-700 hover:bg-brand-100"
            title={`${openComments} open ${openComments === 1 ? "comment" : "comments"}`}
            onClick={onComment}
          >
            {openComments} {openComments === 1 ? "comment" : "comments"}
          </button>
        )}
        {/* Everything this widget can be asked to do, behind one button.
            The controls used to stand in a row here and left a narrow tile's
            title a few characters wide. Copy and expand are on it for readers
            as well as authors: a shared link is where somebody most wants the
            numbers in their own report, and where a map most needs the screen. */}
        <WidgetMenu
          label={name}
          always={editing}
          onOpen={() => setCopyable(copyableIn(body.current))}
          groups={[
            [
              ...(copyable
                ? [
                    {
                      label:
                        copyable === "table"
                          ? "Copy the table, for Excel"
                          : "Copy as a picture",
                      onClick: handOver,
                    },
                  ]
                : []),
              ...(payload && !payload.error
                ? [
                    {
                      label: "Fill the window",
                      onClick: () => setExpanded(true),
                    },
                  ]
                : []),
              ...(onComment
                ? [
                    {
                      label: openComments
                        ? `Comments (${openComments})`
                        : "Comment on this",
                      onClick: onComment,
                    },
                  ]
                : []),
            ],
            // Which page a widget belongs on is usually decided after it is
            // built, and rebuilding it somewhere else is not an answer.
            canEdit && pageNames.length > 1
              ? pageNames.map((page, index) => ({
                  label: `Move to ${page}`,
                  checked: (widget.page ?? 0) === index,
                  onClick: () => onMove(index),
                }))
              : [],
            canEdit
              ? [
                  { label: "Edit this widget", onClick: onEdit },
                  // Removal used to live only inside Arrange mode with nothing
                  // saying so, which read as "widgets cannot be removed".
                  {
                    label: "Remove from dashboard",
                    onClick: onRemove,
                    danger: true,
                  },
                ]
              : [],
          ]}
        />
      </header>
      <div
        ref={body}
        className="flex min-h-0 flex-1 flex-col overflow-auto px-4 pb-2 pt-4"
      >
        {/* A filter the widget's dataset has no column for is dropped rather
            than failing the query - which otherwise looks like a broken
            filter, since the widget goes on showing every row in silence. */}
        {payload?.filters_ignored?.length > 0 && (
          <p className="mb-2 shrink-0 text-[11px] text-amber-700">
            Not filtered by {payload.filters_ignored.join(", ")} - this widget's
            dataset does not have{" "}
            {payload.filters_ignored.length > 1 ? "those" : "that"}{" "}
            {payload.filters_ignored.length > 1 ? "variables" : "variable"}.
          </p>
        )}
        {content}
      </div>

      {/* A figure caption: below the thing it describes, as in a report, and
          out of the way of the data at the top where the eye lands first.
          shrink-0 so a long one is never squeezed to nothing by the chart
          above it. */}
      {/* Any widget, filling the window. A tile the size of a postcard is no
          way to read a table of forty rows or find one red pin, and the answer
          people otherwise reach for is rebuilding the board bigger. The
          dashboard behind it keeps running, so closing this puts the reader
          back exactly where they were. */}
      {expanded &&
        payload &&
        !payload.error &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex flex-col p-3"
            role="dialog"
            aria-label={`${name}, full screen`}
            // The dashboard's own ground, under the widget, exactly as on the
            // board. A widget with no colour of its own is see-through, and put
            // on plain white it changed character entirely: a pale chart built
            // to sit on a dark board arrived as pale on white and unreadable.
            style={ground ?? { backgroundColor: "#ffffff" }}
            // Escape closes it, which is where the hand goes before it finds a
            // button, and the dialog takes focus so the key reaches it.
            tabIndex={-1}
            ref={(node) => node?.focus()}
            onKeyDown={(event) => {
              if (event.key === "Escape") setExpanded(false);
            }}
          >
            {/* The same card, at the size of the window: its colour, its
              transparency, its font and its text colour. Blowing a widget up
              should make it bigger and change nothing else. */}
            <div
              className={`aero-surface flex min-h-0 flex-1 flex-col rounded-card p-3 ${widgetTone(style)}`}
              style={card}
            >
              <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
                <h2
                  className="truncate text-sm font-semibold text-ink-800"
                  style={titleStyle(style)}
                >
                  {name}
                </h2>
                <button
                  className="btn-secondary btn-sm"
                  onClick={() => setExpanded(false)}
                >
                  Close
                </button>
              </div>
              <div className="flex min-h-0 flex-1 flex-col overflow-auto">
                {content}
              </div>
              {style.caption && (
                <p
                  className="shrink-0 border-t border-ink-100 px-1 pt-2 text-xs text-ink-500"
                  style={
                    widgetInk(style)
                      ? { color: widgetInk(style), opacity: 0.75 }
                      : undefined
                  }
                >
                  {style.caption}
                </p>
              )}
            </div>
          </div>,
          // Onto the body, escaping the grid. Every widget sits inside an element
          // the layout has given a transform, and a transformed ancestor makes
          // "fixed" mean "fixed to that ancestor" - so the full-screen map opened
          // at the size of the tile it came from, which is the one size it was
          // trying not to be.
          document.body,
        )}

      {style.caption && (
        <p
          className="shrink-0 border-t border-ink-100 px-4 py-2 text-xs leading-snug text-ink-500"
          // Dimmed rather than a second colour to choose: the caption stays
          // subordinate to the title, and on a dark card a fixed grey would be
          // the one line left unreadable.
          style={
            widgetInk(style)
              ? { color: widgetInk(style), opacity: 0.75 }
              : undefined
          }
        >
          {style.caption}
        </p>
      )}
    </div>
  );
}
