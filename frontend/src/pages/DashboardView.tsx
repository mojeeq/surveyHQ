import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useParams } from 'react-router-dom'
import GridLayout, { type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { api, ApiError, shareGrants } from '@/lib/api'
import { copyableIn, copyChart, copyTable, copyText } from '@/lib/clipboard'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { CHART_THEMES, STATUS_COLORS } from '@/lib/charts'
import { formatNumber, formatValue, relativeTime } from '@/lib/format'
import type {
  Appearance,
  BoundaryLayer,
  Chart,
  Dashboard,
  Dataset,
  FilterGroup,
  Indicator,
  Page,
  Widget,
} from '@/lib/types'
import AssignProject from '@/components/AssignProject'
import ChartCard from '@/components/ChartCard'
import ColorPicker from '@/components/ColorPicker'
import HtmlLibrary from '@/components/HtmlLibrary'
import ShareLinks from '@/components/ShareLinks'
import DashboardFilters, {
  controlKey,
  controlsForPage,
  filterableVariables,
  toFilterGroup,
  useDashboardDatasets,
  type FilterControl,
} from '@/components/DashboardFilters'
import CrosstabTable from '@/components/CrosstabTable'
import ErrorBoundary from '@/components/ErrorBoundary'
import MapWidget, {
  BASEMAPS,
  BASEMAP_NAMES,
  DEFAULT_POINT_OPACITY,
  DEFAULT_POINT_SIZE,
  DEFAULT_TILES,
  POINT_ICONS,
  POINT_ICON_NAMES,
  type BoundaryOverlay,
} from '@/components/MapWidget'
import AppearanceModal, {
  canvasStyle,
  isDark,
  TITLE_FONTS,
  titleFontStack,
  useBackgroundImage,
} from '@/components/DashboardAppearance'
import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
} from '@/components/ui'

const COLUMNS = 12
/** text-sm, the size a widget title is when none is chosen. */
const DEFAULT_TITLE_SIZE = 14
/** What a chart's text measures before anybody changes it; see BASE_TEXT. */
const DEFAULT_CHART_TEXT = 12
const ROW_HEIGHT = 74
// Breathing room inside the canvas, so a widget dragged to the far right stops
// short of the edge instead of butting against it.
const CANVAS_PADDING = 16

/** A selection made by clicking a mark, filtering the rest of the page.
 *
 *  `from` is the widget it was clicked on, which is left unfiltered: it is the
 *  thing being clicked, and collapsing it to the one bar just chosen would take
 *  away the means of choosing another.
 */
type CrossFilter = { variable: string; value: string; label: string; from: string }

/** Fold a click-to-filter selection into the page's own filters. */
function withCrossFilter(group: FilterGroup, drill: CrossFilter | null): FilterGroup {
  if (!drill) return group
  return {
    ...group,
    conditions: [
      ...group.conditions,
      // The clicked text is the label shown on the axis, not the stored code.
      { variable: drill.variable, operator: 'eq', value: drill.value, use_label: true },
    ],
  }
}

/** The variable a chart's first grouping is on, which is what a click means. */
function clickedVariable(payload: { grouped_on?: string[] } | undefined): string {
  return payload?.grouped_on?.[0] ?? ''
}

/** Stacks rather than single faces, so a missing font still lands somewhere sane. */
const WIDGET_FONTS: { label: string; value: string }[] = [
  { label: 'Default (Inter)', value: '' },
  { label: 'System', value: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
  { label: 'Serif', value: 'Georgia, "Times New Roman", serif' },
  { label: 'Slab', value: '"Roboto Slab", Rockwell, Georgia, serif' },
  { label: 'Mono', value: 'ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace' },
  { label: 'Condensed', value: '"Arial Narrow", "Roboto Condensed", sans-serif' },
]

const appearanceOf = (dashboard: Dashboard | undefined): Appearance =>
  (dashboard?.appearance ?? {}) as Appearance

/** The styling one widget carries of its own, over the dashboard's. */
export interface WidgetStyle {
  /** A sentence under the widget saying what the reader is looking at. */
  caption?: string
  background?: string
  /** 0-1. Falls back to the dashboard's when this widget sets none. */
  opacity?: number
  font_family?: string
  font_color?: string
  /** The widget title's own size in pixels, over the card's. */
  title_size?: number
  /** The widget title's own typeface, named from TITLE_FONTS. */
  title_font?: string
  /** Where the title sits in its bar. Left unless asked otherwise. */
  title_align?: 'left' | 'center' | 'right'
  /** How far the card is lifted off the background: none, soft or strong. */
  shadow?: 'none' | 'soft' | 'strong'
  /** The colour this widget's chart leads with. */
  series_color?: string
  /**
   * Print the value on each mark of this widget's chart.
   *
   * Set here as well as on the saved chart, because whether the numbers belong
   * on the bars is a question about the tile they are read in, not about the
   * query: the same chart wants them on a quarter-width tile on a wall and off
   * on a crowded page.
   */
  show_values?: boolean
  /** How big the text on this widget's chart is, in pixels. */
  chart_font_size?: number
}

/**
 * The face of one widget's title.
 *
 * The colour is set here rather than left to inherit from the card: the
 * heading carries a text colour of its own, and an inherited one never gets
 * past it - which is why choosing a text colour used to change the axes and
 * leave the title alone.
 */
function titleStyle(style: WidgetStyle): CSSProperties | undefined {
  const stack = titleFontStack(style.title_font)
  const css: CSSProperties = {
    ...(style.title_size ? { fontSize: `${style.title_size}px`, lineHeight: 1.25 } : {}),
    ...(stack ? { fontFamily: stack } : {}),
    ...(widgetInk(style) ? { color: widgetInk(style) } : {}),
  }
  return Object.keys(css).length ? css : undefined
}

export const styleOf = (widget: Widget): WidgetStyle =>
  (widget.config ?? {}) as WidgetStyle

/** Text light enough to read on a widget dark enough to need it. */
const ON_DARK = '#e8ecf2'

/**
 * The colour this widget's text should be, or nothing to leave it alone.
 *
 * A colour somebody chose always wins. Where they chose none but gave the
 * widget a dark background, the answer is not "the default": the default is
 * near-black, and a black widget with near-black labels is a black rectangle.
 * Choosing a background should not oblige anybody to go and choose a text
 * colour to go with it.
 */
function widgetInk(style: WidgetStyle): string | undefined {
  if (style.font_color) return style.font_color
  return isDark(style.background) ? ON_DARK : undefined
}

/** The card colour for one widget, at its own transparency or the dashboard's.
 *
 *  A widget colour and the see-through setting are two different wishes, and
 *  doing one should not cancel the other - so the colour is the one chosen and
 *  the alpha is whichever applies. Transparency used to be the dashboard's
 *  alone, which made one widget impossible to lift off a busy background
 *  without lifting all of them.
 */
/**
 * How far a widget is lifted off the dashboard behind it.
 *
 * Written out rather than left to Tailwind's shadow classes because these have
 * to go into an inline style beside the card's own colour, and because a
 * dashboard on a coloured or photographic background needs a shadow with more
 * weight in it than a shadow designed for white paper.
 */
const SHADOWS: Record<string, string> = {
  none: 'none',
  soft: '0 1px 2px rgba(15,23,42,.06), 0 4px 12px rgba(15,23,42,.08)',
  strong: '0 2px 4px rgba(15,23,42,.10), 0 12px 28px rgba(15,23,42,.18)',
}

function cardStyle(widget: Widget, dashboardOpacity: number): CSSProperties | undefined {
  const style = styleOf(widget)
  const own = style.opacity
  const opacity = own === undefined || own === null ? dashboardOpacity : own
  const text: CSSProperties = {
    ...(style.font_family ? { fontFamily: style.font_family } : {}),
    ...(widgetInk(style) ? { color: widgetInk(style) } : {}),
    ...(style.shadow && SHADOWS[style.shadow]
      ? { boxShadow: SHADOWS[style.shadow] }
      : {}),
  }
  const chosen = style.background
  if (!chosen) {
    return opacity < 1
      ? { backgroundColor: `rgba(255,255,255,${opacity})`, ...text }
      : Object.keys(text).length
        ? text
        : undefined
  }
  const hex = chosen.replace('#', '')
  if (hex.length !== 6) return { backgroundColor: chosen, ...text }
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return { backgroundColor: `rgba(${r},${g},${b},${opacity})`, ...text }
}

export default function DashboardView({ publicToken }: { publicToken?: string }) {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [activePage, setActivePage] = useState(0)
  const [filterValues, setFilterValues] = useState<Record<string, string>>({})
  /** What was clicked on a chart, filtering the rest of the page by it. */
  const [drill, setDrill] = useState<CrossFilter | null>(null)
  useEffect(() => setDrill(null), [activePage])
  const [editingFilters, setEditingFilters] = useState(false)
  const [editingStyle, setEditingStyle] = useState(false)
  const [editingWidget, setEditingWidget] = useState<Widget | null>(null)
  const [width, setWidth] = useState(1200)
  const [sharing, setSharing] = useState(false)

  const isPublic = Boolean(publicToken)
  const basePath = isPublic ? `/public/dashboards/${publicToken}` : `/dashboards/${id}`

  const dashboard = useQuery({
    queryKey: ['dashboard', id, publicToken],
    queryFn: () => api.get<Dashboard>(basePath),
  })

  // 401 on a public path means the link is password protected and this reader
  // has not given it yet; any other error is a real one.
  const locked =
    isPublic && (dashboard.error as ApiError | null)?.status === 401

  const filterControls: FilterControl[] = (dashboard.data?.filters ??
    []) as unknown as FilterControl[]

  const pages = (dashboard.data?.pages ?? []) as { name?: string }[]
  // A dashboard with no named pages is one unnamed page, which is what every
  // dashboard made before this feature is.
  const pageCount = Math.max(1, pages.length)
  const page = Math.min(activePage, pageCount - 1)
  const pageNames = Array.from(
    { length: pageCount },
    (_, index) => pages[index]?.name || `Page ${index + 1}`,
  )
  // Pages ask different questions, so each carries its own filters.
  const pageControls = controlsForPage(filterControls, page)

  // How much board there is to arrange on. More columns is finer placement
  // rather than more room; a canvas wider than the window is more room, and
  // scrolls sideways to reach it.
  const columns = Number(appearanceOf(dashboard.data).columns) || COLUMNS
  const rowHeight = Number(appearanceOf(dashboard.data).row_height) || ROW_HEIGHT
  const fixedWidth = Number(appearanceOf(dashboard.data).canvas_width) || 0
  const declaredOpacity = appearanceOf(dashboard.data).widget_opacity
  // Opaque unless asked otherwise, and never so faint that the text on it
  // stops being readable against whatever is behind.
  const widgetOpacity = Math.min(1, Math.max(0.3, Number(declaredOpacity ?? 1)))
  const canvasWidth = Math.max(fixedWidth || width, 320)

  // The grid needs a width in pixels, and it has to keep up with the window.
  //
  // This used to read clientWidth in a callback ref, which React calls when
  // the node is attached and never again: the board was laid out for whatever
  // the window was at load and stayed that way, so widening the browser left a
  // strip of empty space and narrowing it cut the right-hand widgets off. The
  // observer goes on the ref rather than in an effect so it is attached and
  // detached with the node itself, and it catches the window, the sidebar
  // collapsing and a phone turning sideways alike - all one event to the grid.
  const watcher = useRef<ResizeObserver | null>(null)
  const measureGrid = useCallback((node: HTMLDivElement | null) => {
    watcher.current?.disconnect()
    watcher.current = null
    if (!node) return
    setWidth(node.clientWidth)
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect.width
      // A container measured at nothing is a hidden tab, not a narrow one.
      // Laying the board out for a zero-width canvas would stack every widget
      // into a single column before the page has even been looked at.
      if (measured && measured > 0) setWidth(Math.round(measured))
    })
    observer.observe(node)
    watcher.current = observer
  }, [])

  const rendered = useQuery({
    // The values are part of the key, so changing a filter refetches rather
    // than showing the previous selection's numbers under the new label. So is
    // the page, whose filters are its own.
    queryKey: ['dashboard-data', id, publicToken, activePage, filterValues, drill],
    queryFn: () =>
      api.post<{ widgets: Record<string, any> }>(
        `${basePath}/data${drill ? `?every_widget_but=${drill.from}` : ''}`,
        withCrossFilter(toFilterGroup(pageControls, filterValues), drill),
      ),
    enabled: Boolean(dashboard.data),
    // Keep showing the numbers already on screen while the filtered ones are
    // fetched. Every filter change is a new query key, so without this each
    // one tore the whole board down to spinners and rebuilt it - and going
    // back to a selection you had already made was smooth only because that
    // key happened to be cached. Now both directions read the same.
    placeholderData: keepPreviousData,
    refetchInterval: dashboard.data?.refresh_interval_seconds
      ? dashboard.data.refresh_interval_seconds * 1000
      : false,
  })

  const saveLayout = useMutation({
    mutationFn: (widgets: Widget[]) =>
      api.patch(`/dashboards/${id}`, {
        widgets: widgets.map((widget) => ({
          id: widget.id,
          title: widget.title,
          widget_type: widget.widget_type,
          chart_id: widget.chart_id,
          indicator_id: widget.indicator_id,
          dataset_id: widget.dataset_id,
          config: widget.config,
          layout: widget.layout,
          position: widget.position,
          page: widget.page ?? 0,
        })),
      }),
    onSuccess: () => {
      toast.push('Layout saved', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const share = useMutation({
    mutationFn: (enable: boolean) =>
      api.post<Dashboard>(`/dashboards/${id}/share?enable=${enable}`),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      if (updated.public_token) {
        const url = `${location.origin}/shared/${updated.public_token}`
        // Told after the attempt rather than before it: on a plain HTTP
        // deployment the browser has no clipboard object at all, and saying
        // "copied" when nothing was is worse than saying nothing.
        copyText(url).then((copied) =>
          toast.push(
            copied ? 'Public link copied to your clipboard' : 'This dashboard is now shared',
            'success',
          ),
        )
      } else {
        toast.push('Public sharing turned off', 'info')
      }
    },
  })

  const saveTheme = useMutation({
    mutationFn: (theme: string) => api.patch(`/dashboards/${id}`, { theme }),
    onSuccess: () => {
      toast.push('Palette changed', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const savePages = useMutation({
    mutationFn: (pages: { name: string }[]) => api.patch(`/dashboards/${id}`, { pages }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard', id] }),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const movePage = useMutation({
    mutationFn: ({ from, to }: { from: number; to: number }) =>
      api.post(`/dashboards/${id}/pages/move`, { from, to }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      // Stay on the page that moved rather than on the position it left.
      setActivePage(variables.to)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const removePage = useMutation({
    mutationFn: (index: number) => api.delete(`/dashboards/${id}/pages/${index}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard', id] }),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const moveWidget = useMutation({
    mutationFn: ({ widgetId, page }: { widgetId: string; page: number }) =>
      api.patch(`/dashboards/${id}/widgets/${widgetId}`, { page }),
    onSuccess: (_data, variables) => {
      toast.push('Widget moved', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      // Follow it, so the move can be seen rather than just reported.
      setActivePage(variables.page)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const removeWidget = useMutation({
    mutationFn: (widgetId: string) => api.delete(`/dashboards/${id}/widgets/${widgetId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', id] })
    },
  })

  const allWidgets = dashboard.data?.widgets ?? []
  const widgets = useMemo(
    () => allWidgets.filter((widget) => (widget.page ?? 0) === page),
    [allWidgets, page],
  )

  const appearance = appearanceOf(dashboard.data)
  const backgroundUrl = useBackgroundImage(basePath, appearance)
  const logoUrl = useBackgroundImage(basePath, appearance, 'logo')
  const canvas = canvasStyle(appearance, backgroundUrl)
  const onDarkGround = Boolean(canvas) && isDark(appearance.background_color)
  // The tabs sit on their own band when one is set, so what they have to stay
  // readable against is that band rather than the dashboard's background.
  const tabsOnDark = appearance.tab_background
    ? isDark(appearance.tab_background)
    : onDarkGround

  const layout: Layout[] = useMemo(
    () =>
      widgets.map((widget, index) => ({
        i: widget.id,
        x: Number(widget.layout?.x ?? (index % 2) * 6),
        y: Number(widget.layout?.y ?? Math.floor(index / 2) * 4),
        w: Number(widget.layout?.w ?? 6),
        h: Number(widget.layout?.h ?? 4),
        minW: 2,
        minH: 2,
      })),
    [widgets],
  )

  if (dashboard.isLoading) return <Loading />
  // A link with a password answers 401 until it is given. That is a door, not
  // a fault, so it gets a door rather than an error banner.
  if (locked)
    return (
      <SharePasswordPrompt
        token={publicToken!}
        onUnlocked={() => {
          queryClient.invalidateQueries()
          dashboard.refetch()
        }}
      />
    )
  if (dashboard.error) return <ErrorNote error={dashboard.error} retry={dashboard.refetch} />

  const onLayoutChange = (next: Layout[]) => {
    if (!editing) return
    // Every widget goes back, not just this page's: the PATCH replaces the whole
    // list, so omitting the other pages would delete them.
    const updated = allWidgets.map((widget) => {
      const position = next.find((item) => item.i === widget.id)
      return position
        ? { ...widget, layout: { x: position.x, y: position.y, w: position.w, h: position.h } }
        : widget
    })
    saveLayout.mutate(updated)
  }

  return (
    <div>
      <PageHeader
        title={dashboard.data!.name}
        description={appearance.hide_subtitle ? undefined : dashboard.data!.description}
        logo={
          logoUrl ? (
            <img
              src={logoUrl}
              alt=""
              style={{ height: appearance.logo_height ?? 32 }}
              className="w-auto shrink-0 object-contain"
            />
          ) : undefined
        }
        titleStyle={{
          fontSize: appearance.title_size ? `${appearance.title_size}px` : undefined,
          fontFamily: titleFontStack(appearance.title_font),
          color: appearance.title_color || undefined,
          lineHeight: 1.15,
        }}
        align={appearance.title_align ?? 'left'}
        rule={Boolean(appearance.header_rule)}
        onTitleClick={
          !isPublic && can('analyst') ? () => setEditingStyle(true) : undefined
        }
        actions={
          !isPublic && (
            <>
              <AssignProject
                kind="dashboard"
                id={dashboard.data!.id}
                projectId={dashboard.data!.project_id}
                canMove={can('manager')}
              />
              {can('analyst') && (
                <>
                  <select
                    className="input w-44"
                    title="Chart colours for this dashboard"
                    value={dashboard.data!.theme ?? 'default'}
                    onChange={(event) => saveTheme.mutate(event.target.value)}
                  >
                    {Object.entries(CHART_THEMES).map(([key, theme]) => (
                      <option key={key} value={key}>
                        {theme.label}
                      </option>
                    ))}
                  </select>
                  <button className="btn-secondary" onClick={() => setEditingFilters(true)}>
                    Filters
                  </button>
                  <button className="btn-secondary" onClick={() => setEditingStyle(true)}>
                    Appearance
                  </button>
                  <button className="btn-secondary" onClick={() => setAdding(true)}>
                    Add widget
                  </button>
                  <button
                    className={editing ? 'btn-primary' : 'btn-secondary'}
                    onClick={() => setEditing(!editing)}
                  >
                    {editing ? 'Done' : 'Move & resize'}
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => {
                      // Publishing and managing the addresses are the same
                      // button now: a board that is not shared yet becomes
                      // shared by being given its first link.
                      if (!dashboard.data!.is_public) share.mutate(true)
                      setSharing(true)
                    }}
                  >
                    Share
                  </button>
                </>
              )}
            </>
          )
        }
      />

      {dashboard.data!.is_public && !isPublic && (
        <PublicLinkBar dashboard={dashboard.data!} canEdit={can('analyst')} />
      )}

      {sharing && !isPublic && (
        <ShareLinks dashboard={dashboard.data!} onClose={() => setSharing(false)} />
      )}

      {/* Everything the dashboard is read for sits on the canvas: the filters
          in use, the pages, and the widgets. The page header stays off it, so
          the toolbar's buttons keep the contrast they were designed with. */}
      <div
        className={canvas ? 'rounded-card p-4' : ''}
        style={canvas}
        data-testid="dashboard-canvas"
      >
      {drill && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-card border border-brand-300 bg-brand-50 px-3 py-2 text-sm text-brand-900">
          <Badge tone="info" icon="⊙">
            Filtered by a click
          </Badge>
          <span>
            <span className="font-mono text-xs">{drill.variable}</span> is{' '}
            <strong>{drill.value}</strong>
          </span>
          <span className="text-xs text-brand-800/70">
            - every widget on this page except &ldquo;{drill.label}&rdquo;
          </span>
          <button className="btn-ghost btn-sm ml-auto" onClick={() => setDrill(null)}>
            Clear
          </button>
        </div>
      )}

      <DashboardFilters
        basePath={basePath}
        labelColor={appearance.filter_color}
        background={appearance.filter_background}
        controls={pageControls}
        value={filterValues}
        onChange={setFilterValues}
      />

      <PageTabs
        pages={pages}
        active={page}
        count={pageCount}
        canEdit={!isPublic && can('analyst')}
        widgetsOnPage={widgets.length}
        onDark={tabsOnDark}
        band={appearance.tab_background}
        color={appearance.tab_color}
        onSelect={setActivePage}
        onChange={(next) => savePages.mutate(next)}
        onMove={(from, to) => movePage.mutate({ from, to })}
        onRemove={(index) => removePage.mutate(index)}
      />

      {!widgets.length ? (
        <Card>
          <EmptyState
            icon="▦"
            title="This dashboard is empty"
            description="Add saved charts or indicators to build your monitoring view."
            action={
              !isPublic &&
              can('analyst') && (
                <button className="btn-primary btn-sm" onClick={() => setAdding(true)}>
                  Add your first widget
                </button>
              )
            }
          />
        </Card>
      ) : (
        <div
          ref={measureGrid}
          // Dimmed a little while the numbers on screen belong to the previous
          // selection, so a click is acknowledged without the board being torn
          // down. isPlaceholderData rather than isFetching on purpose: the
          // latter is also true on the timed refresh, which would make a
          // dashboard left up on a wall blink every minute for no reason.
          className={`${fixedWidth > width ? 'overflow-x-auto' : ''} transition-opacity duration-200 ${
            rendered.isPlaceholderData ? 'opacity-60' : 'opacity-100'
          }`}
        >
        <GridLayout
          className="layout"
          layout={layout}
          cols={columns}
          rowHeight={rowHeight}
          width={canvasWidth}
          // Without an explicit width the container stays as wide as the
          // window while the widgets inside it are laid out for the wider
          // canvas, so there is nothing for the scroller to scroll.
          style={fixedWidth ? { width: canvasWidth } : undefined}
          margin={[16, 16]}
          containerPadding={[CANVAS_PADDING, CANVAS_PADDING]}
          isDraggable={editing && !isPublic}
          isResizable={editing && !isPublic}
          onDragStop={onLayoutChange}
          onResizeStop={onLayoutChange}
          draggableHandle=".widget-handle"
        >
          {widgets.map((widget) => (
            <div
              key={widget.id}
              className="card overflow-hidden"
              // A widget's own colour if it has one, the dashboard's paper if
              // not - and either way the dashboard's transparency, so the
              // background shows through both the same amount. The charts
              // inside draw on a transparent canvas, so they come with it.
              style={cardStyle(widget, widgetOpacity)}
            >
              <ErrorBoundary what={`"${widget.title || 'this widget'}"`}>
              <WidgetFrame
                widget={widget}
                card={cardStyle(widget, widgetOpacity)}
                ground={canvas}
                payload={rendered.data?.widgets[widget.id]}
                loading={rendered.isLoading}
                editing={editing && !isPublic}
                canEdit={!isPublic && can('analyst')}
                theme={dashboard.data!.theme ?? 'default'}
                pageNames={pageNames}
                basePath={basePath}
                onMove={(toPage) => moveWidget.mutate({ widgetId: widget.id, page: toPage })}
                onEdit={() => setEditingWidget(widget)}
                onRemove={() => {
                  if (confirm(`Remove "${widget.title || 'this widget'}" from the dashboard?`))
                    removeWidget.mutate(widget.id)
                }}
                onSelect={(variable, value) =>
                  setDrill((current) =>
                    // Clicking the same mark again is how you undo it, which is
                    // where the hand goes before it finds the chip.
                    current && current.variable === variable && current.value === value
                      ? null
                      : { variable, value, label: widget.title || variable, from: widget.id },
                  )
                }
              />
              </ErrorBoundary>
            </div>
          ))}
        </GridLayout>
        </div>
      )}
      </div>

      {adding && (
        <AddWidgetModal
          dashboardId={id}
          projectId={dashboard.data!.project_id}
          page={page}
          onClose={() => setAdding(false)}
        />
      )}
      {editingWidget && (
        <EditWidgetModal
          dashboardId={id}
          projectId={dashboard.data!.project_id}
          widget={editingWidget}
          pageNames={pageNames}
          dashboardOpacity={widgetOpacity}
          onClose={() => setEditingWidget(null)}
        />
      )}
      {editingStyle && (
        <AppearanceModal
          dashboardId={id}
          appearance={appearance}
          widgets={allWidgets}
          onClose={() => setEditingStyle(false)}
        />
      )}
      {editingFilters && (
        <FilterControlsModal
          dashboardId={id}
          page={page}
          pageName={pageNames[page]}
          widgets={widgets}
          controls={filterControls}
          onClose={() => setEditingFilters(false)}
        />
      )}
    </div>
  )
}


/** One line on a widget's menu. */
type MenuItem = {
  label: string
  onClick: () => void
  /** A tick down the left, for the choice that is already in force. */
  checked?: boolean
  danger?: boolean
}

/**
 * Everything you can do to a widget, behind one button.
 *
 * These used to sit side by side in the title bar - copy, expand, which page,
 * edit, remove - and on a narrow tile they left the title a few characters
 * wide. A menu costs one more click on things nobody does twice a minute and
 * gives the title the bar back.
 *
 * The menu is portalled to the body and placed from the button's own position.
 * A widget sits inside a card that clips what overflows it, and inside a grid
 * that has been given a transform, so a panel positioned any other way is
 * either cut off at the card's edge or fixed to the wrong thing entirely.
 */
function WidgetMenu({ groups, label, always, onOpen }: {
  /** Items in bands, drawn with a rule between them. Empty bands are dropped. */
  groups: MenuItem[][]
  label: string
  /** Show the button without hovering, e.g. while the board is being arranged. */
  always?: boolean
  /**
   * Called as the menu opens, to settle anything the items depend on.
   *
   * What a widget can be copied as is read off what it actually drew, and a
   * chart's canvas appears a moment after the data does - so a check made
   * when the data arrived found nothing, and the copy line was missing from
   * the menu for the life of the page. Asking at the moment of opening is
   * both later and cheaper than watching for it.
   */
  onOpen?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState<{ top: number; right: number } | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const bands = groups.filter((band) => band.length > 0)

  // Anywhere else, and the next key, closes it. Both are what a menu is
  // expected to do, and neither is worth a click on a "cancel".
  useEffect(() => {
    if (!open) return
    const away = (event: MouseEvent) => {
      const target = event.target as Node
      // The menu itself counts as inside. Listening in the capture phase means
      // this runs before anything the menu could do to stop it, so testing the
      // button alone closed the menu on the way down and the item under the
      // pointer was gone before its click arrived: every entry did nothing.
      if (button.current?.contains(target) || panel.current?.contains(target)) return
      setOpen(false)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    // Captured, so a click on the page behind closes the menu instead of
    // reaching whatever was under the pointer.
    document.addEventListener('mousedown', away, true)
    document.addEventListener('keydown', key)
    window.addEventListener('resize', () => setOpen(false), { once: true })
    return () => {
      document.removeEventListener('mousedown', away, true)
      document.removeEventListener('keydown', key)
    }
  }, [open])

  const show = () => {
    const box = button.current?.getBoundingClientRect()
    if (box) setAt({ top: box.bottom + 4, right: Math.max(8, window.innerWidth - box.right) })
    if (!open) onOpen?.()
    setOpen((was) => !was)
  }

  if (!bands.length) return null

  return (
    <>
      <button
        ref={button}
        className={`btn-ghost btn-sm shrink-0 px-1.5 text-ink-500 transition-opacity ${
          always || open ? 'opacity-100' : 'opacity-0 focus:opacity-100 group-hover:opacity-100'
        }`}
        onClick={show}
        title={`Options for ${label}`}
        aria-label={`Options for ${label}`}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {/* Three dots, drawn rather than typed: the character for them is
            missing from enough fonts to come out as a box. */}
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
          <circle cx="3" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="13" cy="8" r="1.5" />
        </svg>
      </button>
      {open &&
        at &&
        createPortal(
          <div
            ref={panel}
            className="fixed z-50 min-w-[11rem] overflow-hidden rounded-card border border-ink-200 bg-white py-1 shadow-lg"
            style={{ top: at.top, right: at.right }}
            role="menu"
          >
            {bands.map((band, index) => (
              <div key={index} className={index ? 'mt-1 border-t border-ink-100 pt-1' : ''}>
                {band.map((item) => (
                  <button
                    key={item.label}
                    role="menuitem"
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-ink-50 ${
                      item.danger ? 'text-red-600' : 'text-ink-700'
                    }`}
                    onClick={() => {
                      setOpen(false)
                      item.onClick()
                    }}
                  >
                    <span className="w-3 shrink-0 text-ink-400">{item.checked ? '\u2713' : ''}</span>
                    {item.label}
                  </button>
                ))}
              </div>
            ))}
          </div>,
          document.body,
        )}
    </>
  )
}

function WidgetFrame({
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
}: {
  widget: Widget
  payload: any
  loading: boolean
  editing: boolean
  canEdit: boolean
  /** The tile's own colour, so the expanded view is the same widget. */
  card?: CSSProperties
  /** What the dashboard lays behind its widgets, under a see-through one. */
  ground?: CSSProperties
  /** Where this dashboard's own resources live, shared or signed in. */
  basePath: string
  /** The dashboard's categorical ordering, applied to every chart on it. */
  theme: string
  /** Every page on this dashboard, so a widget can be sent to another one. */
  pageNames: string[]
  onMove: (page: number) => void
  onEdit: () => void
  onRemove: () => void
  /** A mark was clicked: filter the rest of the page by what it stands for. */
  onSelect?: (variable: string, value: string) => void
}) {
  const style = styleOf(widget)
  const body = useRef<HTMLDivElement>(null)
  const toast = useToast()
  const [expanded, setExpanded] = useState(false)
  const name = widget.title || payload?.name || 'Widget'

  // What this widget can be handed over as, judged from what it actually drew
  // rather than from its type: a chart shown as a table is a table to copy.
  const [copyable, setCopyable] = useState<'table' | 'chart' | null>(null)
  useEffect(() => {
    setCopyable(copyableIn(body.current))
  }, [payload, expanded])

  const handOver = async () => {
    const node = body.current
    if (!node) return
    try {
      const table = node.querySelector('table')
      if (table) {
        toast.push(await copyTable(table as HTMLTableElement), 'success')
        return
      }
      const canvas = node.querySelector('canvas')
      if (canvas) toast.push(await copyChart(canvas as HTMLCanvasElement, name), 'success')
    } catch (error) {
      toast.push((error as Error).message, 'error')
    }
  }

  // The widget itself, so the same thing can be drawn in the tile and, at
  // the size of the window, in the overlay below. Written once because the
  // two must not drift: an expanded widget showing something subtly
  // different from the tile it came from would be worse than no overlay.
  const content = loading ? (
      <Loading />
    ) : !payload ? (
      <p className="py-6 text-center text-sm text-ink-400">No data</p>
    ) : payload.error ? (
      <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        {payload.error}
      </p>
    ) : payload.type === 'indicator' ? (
      <IndicatorWidget payload={payload} theme={theme} onSelect={onSelect} />
    ) : payload.type === 'quality' ? (
      <QualityWidget payload={payload} />
    ) : payload.type === 'crosstab' ? (
      <CrosstabTable
        result={payload.result}
        compact
        fill
        // A cross-tab carries both its variables in the result, so it can
        // say which one a heading belongs to without the server naming it.
        onSelect={onSelect}
      />
    ) : payload.type === 'freshness' ? (
      <FreshnessWidget payload={payload} />
    ) : payload.type === 'map' ? (
      <BoundedMap payload={payload} widget={widget} basePath={basePath} />
    ) : payload.type === 'html' ? (
      <HtmlWidget html={payload.html ?? ''} />
    ) : payload.type === 'countdown' ? (
      <CountdownWidget payload={payload} />
    ) : payload.type === 'text' ? (
      <p className="whitespace-pre-wrap text-sm text-ink-700">{payload.content}</p>
    ) : payload.result ? (
      <ChartCard
        result={payload.result}
        chartType={payload.chart_type ?? 'bar'}
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
          ...(style.show_values === undefined ? {} : { showValues: style.show_values }),
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
  ) : null

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
            editing ? 'cursor-move' : ''
          } ${
            // grow so the alignment has room to act in: a title sized to its
            // own text is already centred inside itself and centring it again
            // does nothing visible.
            style.title_align === 'center'
              ? 'flex-1 text-center'
              : style.title_align === 'right'
                ? 'flex-1 text-right'
                : ''
          }`}
          style={titleStyle(style)}
        >
          {widget.title || payload?.name || 'Widget'}
        </h3>
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
                        copyable === 'table'
                          ? 'Copy the table, for Excel'
                          : 'Copy as a picture',
                      onClick: handOver,
                    },
                  ]
                : []),
              ...(payload && !payload.error
                ? [{ label: 'Fill the window', onClick: () => setExpanded(true) }]
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
                  { label: 'Edit this widget', onClick: onEdit },
                  // Removal used to live only inside Arrange mode with nothing
                  // saying so, which read as "widgets cannot be removed".
                  { label: 'Remove from dashboard', onClick: onRemove, danger: true },
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
            Not filtered by {payload.filters_ignored.join(', ')} - this widget's
            dataset does not have {payload.filters_ignored.length > 1 ? 'those' : 'that'}{' '}
            {payload.filters_ignored.length > 1 ? 'variables' : 'variable'}.
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
          style={ground ?? { backgroundColor: '#ffffff' }}
          // Escape closes it, which is where the hand goes before it finds a
          // button, and the dialog takes focus so the key reaches it.
          tabIndex={-1}
          ref={(node) => node?.focus()}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setExpanded(false)
          }}
        >
          {/* The same card, at the size of the window: its colour, its
              transparency, its font and its text colour. Blowing a widget up
              should make it bigger and change nothing else. */}
          <div
            className="aero-surface flex min-h-0 flex-1 flex-col rounded-card p-3"
            style={card}
          >
            <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
              <h2 className="truncate text-sm font-semibold text-ink-800" style={titleStyle(style)}>
                {name}
              </h2>
              <button className="btn-secondary btn-sm" onClick={() => setExpanded(false)}>
                Close
              </button>
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-auto">{content}</div>
            {style.caption && (
              <p
                className="shrink-0 border-t border-ink-100 px-1 pt-2 text-xs text-ink-500"
                style={widgetInk(style) ? { color: widgetInk(style), opacity: 0.75 } : undefined}
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
          style={widgetInk(style) ? { color: widgetInk(style), opacity: 0.75 } : undefined}
        >
          {style.caption}
        </p>
      )}
    </div>
  )
}

/**
 * The state of a dataset's data quality checks.
 *
 * Failing checks are listed first and in full; passing ones are a count. A
 * panel that lists thirty green rows buries the one red one, which is the only
 * row anybody opened the dashboard to see.
 */
/**
 * Pages across a dashboard.
 *
 * Hidden entirely until there is more than one, so a dashboard that does not
 * use pages does not grow a tab strip saying "Page 1". Adding the second page
 * has to name the first as well, since an unnamed page cannot be labelled.
 */
function PageTabs({
  pages,
  active,
  count,
  canEdit,
  widgetsOnPage,
  onDark,
  band,
  color,
  onSelect,
  onChange,
  onMove,
  onRemove,
}: {
  pages: { name?: string }[]
  active: number
  count: number
  canEdit: boolean
  widgetsOnPage: number
  /** Set when whatever is behind the tabs is dark enough to swallow ink text. */
  onDark: boolean
  /** A colour to lay behind the strip, for a background that swallows it. */
  band?: string
  /** The tab text, chosen rather than worked out from what is behind it. */
  color?: string
  onSelect: (index: number) => void
  onChange: (pages: { name: string }[]) => void
  onMove: (from: number, to: number) => void
  onRemove: (index: number) => void
}) {
  const named = Array.from({ length: count }, (_, index) => ({
    name: pages[index]?.name || `Page ${index + 1}`,
  }))

  /** Two tabs reading the same word cannot be told apart. */
  const taken = (name: string, except = -1) =>
    named.some((page, i) => i !== except && page.name.toLowerCase() === name.toLowerCase())

  const addPage = () => {
    const name = prompt('Name for the new page')?.trim()
    if (!name) return
    if (taken(name)) {
      alert(`This dashboard already has a page called "${name}".`)
      return
    }
    onChange([...named, { name }])
    onSelect(count)
  }

  const renamePage = (index: number) => {
    const name = prompt('Rename this page', named[index].name)?.trim()
    if (!name || name === named[index].name) return
    if (taken(name, index)) {
      alert(`This dashboard already has a page called "${name}".`)
      return
    }
    onChange(named.map((page, i) => (i === index ? { name } : page)))
  }

  const removePage = (index: number) => {
    if (widgetsOnPage > 0) {
      alert('Move or remove this page\u2019s widgets before deleting it.')
      return
    }
    if (!confirm(`Delete the page "${named[index].name}"?`)) return
    // Deleted on the server, which renumbers the pages after it along with
    // their widgets. Filtering the list here would leave those widgets on
    // whichever page ended up at their old number.
    onRemove(index)
    onSelect(Math.max(0, index - 1))
  }

  if (count <= 1 && !canEdit) return null

  return (
    // Two groups, not one run of buttons. The tabs wrap among themselves and
    // the page controls stay together at the end: mixed into one wrapping row,
    // a twelfth tab came to rest between "Rename" and "Delete page", where it
    // reads as one of the controls rather than as a page.
    <div
      className={`mb-4 flex flex-wrap items-end justify-between gap-x-2 border-b ${
        onDark ? 'border-white/25' : 'border-ink-200'
      } ${band ? 'rounded-t-lg px-2' : ''}`}
      style={band ? { backgroundColor: band } : undefined}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-1">
      {(count > 1 || canEdit) &&
        named.map((page, index) => (
          <button
            key={index}
            onClick={() => onSelect(index)}
            onDoubleClick={() => canEdit && renamePage(index)}
            title={canEdit ? 'Double-click to rename, or use the Rename button' : undefined}
            className={`whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors ${
              active === index
                ? onDark
                  ? 'border-white text-white'
                  : 'border-brand-600 text-brand-700'
                : onDark
                  ? 'border-transparent text-white/70 hover:text-white'
                  : 'border-transparent text-ink-500 hover:text-ink-800'
            }`}
            // A chosen colour wins over the light-or-dark guess. The page that
            // is open keeps its underline in that colour too, so which page you
            // are on does not stop being visible when the ink changes.
            style={
              color
                ? {
                    color,
                    borderBottomColor: active === index ? color : 'transparent',
                    opacity: active === index ? 1 : 0.75,
                  }
                : undefined
            }
          >
            {page.name}
          </button>
        ))}
      </div>
      {canEdit && (
        <div className="flex shrink-0 flex-wrap items-center gap-x-1 py-1">
          <button
            className={`btn-ghost btn-sm ${onDark ? 'text-white/80' : 'text-ink-500'}`}
                style={color ? { color, opacity: 0.8 } : undefined}
            onClick={addPage}
          >
            + Page
          </button>
          {/* Renaming used to be a double-click on the tab and nothing said so,
              which is no way to find a feature. */}
          <button
            className={`btn-ghost btn-sm ${onDark ? 'text-white/80' : 'text-ink-500'}`}
                style={color ? { color, opacity: 0.8 } : undefined}
            onClick={() => renamePage(active)}
          >
            Rename
          </button>
          {count > 1 && (
            <>
              <button
                className={`btn-ghost btn-sm ${onDark ? 'text-white/80' : 'text-ink-500'}`}
                style={color ? { color, opacity: 0.8 } : undefined}
                onClick={() => onMove(active, active - 1)}
                disabled={active === 0}
                title="Move this page earlier"
              >
                ◀
              </button>
              <button
                className={`btn-ghost btn-sm ${onDark ? 'text-white/80' : 'text-ink-500'}`}
                style={color ? { color, opacity: 0.8 } : undefined}
                onClick={() => onMove(active, active + 1)}
                disabled={active === count - 1}
                title="Move this page later"
              >
                ▶
              </button>
              <button
                className="btn-ghost btn-sm text-red-600"
                onClick={() => removePage(active)}
              >
                Delete page
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

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
function BoundedMap({
  payload,
  widget,
  basePath,
}: {
  payload: any
  widget: Widget
  basePath: string
}) {
  const boundary = payload.boundary as BoundaryOverlay | undefined
  const areas = useQuery({
    queryKey: ['dashboard-boundary', basePath, boundary?.id],
    queryFn: () => api.get<{ type: string; features: never[] }>(
      `${basePath}/boundaries/${boundary!.id}`,
    ),
    enabled: Boolean(boundary?.id),
    // The frame does not move. Refetching it on every window focus would be
    // the one thing on this page reliably wasting the field office's bandwidth.
    staleTime: 60 * 60 * 1000,
  })

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
  )
}

function HtmlWidget({ html }: { html: string }) {
  if (!html.trim()) {
    return <p className="py-6 text-center text-sm text-ink-400">This embed is empty</p>
  }
  return (
    <iframe
      title="Embedded content"
      srcDoc={html}
      sandbox="allow-scripts allow-popups allow-forms"
      referrerPolicy="no-referrer"
      className="h-full min-h-[120px] w-full border-0"
    />
  )
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
function FreshnessWidget({ payload }: { payload: any }) {
  const lines: any[] = payload.datasets ?? []
  return (
    <div className="flex h-full flex-col gap-2 overflow-auto">
      {lines.map((line) => {
        const colour =
          STATUS_COLORS[line.status as keyof typeof STATUS_COLORS] ?? STATUS_COLORS.unknown
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
              <p className="truncate text-sm font-medium text-ink-800">{line.name}</p>
              <p className="text-xs text-ink-500">
                Imported {relativeTime(line.imported_at)}
                {line.latest_record_at ? (
                  <>
                    {' · newest record '}
                    {relativeTime(line.latest_record_at)}
                  </>
                ) : line.date_variable ? null : (
                  <span className="text-ink-400"> · no date column to read</span>
                )}
              </p>
              {line.error && <p className="text-xs text-amber-700">{line.error}</p>}
            </div>
            <span className="shrink-0 text-xs tabular-nums text-ink-400">
              {formatNumber(line.rows)} rows
            </span>
          </div>
        )
      })}
      {!lines.length && (
        <p className="py-6 text-center text-sm text-ink-400">Nothing to report</p>
      )}
    </div>
  )
}

function CountdownWidget({ payload }: { payload: any }) {
  const target = payload.target ? new Date(payload.target).getTime() : NaN
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!Number.isFinite(target)) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [target])

  if (!Number.isFinite(target)) {
    return <p className="py-6 text-center text-sm text-ink-400">No date set for this countdown</p>
  }

  const remaining = target - now
  if (remaining <= 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
        <p className="text-2xl font-semibold text-red-600">
          {payload.expired_text || 'Time is up'}
        </p>
        <p className="text-xs text-ink-500">
          {payload.label || new Date(target).toLocaleString()}
        </p>
      </div>
    )
  }

  const seconds = Math.floor(remaining / 1000)
  const parts = [
    { value: Math.floor(seconds / 86400), unit: 'days' },
    { value: Math.floor((seconds % 86400) / 3600), unit: 'hours' },
    { value: Math.floor((seconds % 3600) / 60), unit: 'min' },
    { value: seconds % 60, unit: 'sec' },
  ]

  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
      <div className="flex items-end gap-3">
        {parts.map((part) => (
          <div key={part.unit}>
            <div className="text-3xl font-semibold tabular-nums text-ink-900">
              {String(part.value).padStart(2, '0')}
            </div>
            <div className="text-[11px] uppercase tracking-wide text-ink-400">{part.unit}</div>
          </div>
        ))}
      </div>
      <p className="text-xs text-ink-500">
        {payload.label || `until ${new Date(target).toLocaleString()}`}
      </p>
    </div>
  )
}

function QualityWidget({ payload }: { payload: any }) {
  const failing = payload.checks.filter((c: any) => c.passed === false)
  const stale = payload.oldest_run_at
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge tone={payload.failing ? 'danger' : 'success'}>
          {payload.failing ? `${payload.failing} failing` : 'All passing'}
        </Badge>
        {payload.passing > 0 && <Badge tone="neutral">{payload.passing} passing</Badge>}
        {payload.never_run > 0 && (
          <Badge tone="warning">{payload.never_run} never run</Badge>
        )}
      </div>

      {!payload.checks.length ? (
        <p className="text-sm text-ink-500">
          No active checks on {payload.name}.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-2 overflow-auto">
          {failing.map((check: any) => (
            <li
              key={check.id}
              className="rounded-card border border-red-200 bg-red-50 px-3 py-2"
            >
              <p className="text-sm font-medium text-red-900">{check.name}</p>
              <p className="text-xs text-red-800">{check.message}</p>
              {payload.filtered && check.total_rows > 0 && (
                <p className="mt-0.5 text-[11px] text-red-700">
                  {formatNumber(check.failed_rows)} of {formatNumber(check.total_rows)} rows
                  in view
                </p>
              )}
            </li>
          ))}
          {!failing.length && (
            <li className="text-sm text-ink-500">
              Every active check on {payload.name} passed.
            </li>
          )}
        </ul>
      )}

      {payload.filtered ? (
        <p className="mt-2 text-[11px] text-ink-400">
          {/* Counted against the page's filter just now, so there is no "last
              run" to date it by - and saying which it is matters, because the
              two answer different questions about the same rule. */}
          Counted for the filters on this page
        </p>
      ) : (
        stale && (
          <p className="mt-2 text-[11px] text-ink-400">
            {/* Results are shown as last run, not recomputed on open, so say when. */}
            Oldest result {relativeTime(stale)}
          </p>
        )
      )}
    </div>
  )
}

function IndicatorWidget({
  payload,
  theme,
  onSelect,
}: {
  payload: any
  theme: string
  /** Filter the page by a category of this indicator's breakdown. */
  onSelect?: (variable: string, value: string) => void
}) {
  const color = STATUS_COLORS[payload.status as keyof typeof STATUS_COLORS] ?? STATUS_COLORS.unknown
  const breakdown: Record<string, number> = payload.breakdown ?? {}
  const groups = Object.entries(breakdown)

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
    { value: number; target: number | null; percent: number | null; status: string }
  > = payload.breakdown_progress ?? {}
  const hasTargets = groups.some(([key]) => (progress[key]?.target ?? null) !== null)

  // "Lower is better" reads the other way round. A rejection rate with a
  // target of 5% is a ceiling, not something to work towards: the space under
  // it is headroom nobody is trying to fill, so there is no "still to go" -
  // only whether the limit has been passed, which is bad rather than good.
  const lowerIsBetter = payload.direction === 'lower_is_better'

  const overLabel = lowerIsBetter ? 'Over the limit' : 'Over target'
  const achievedLabel = lowerIsBetter ? 'Within the limit' : 'Achieved'
  // Two segments when lower is better, three otherwise. Carrying a "still to
  // go" of zero would put a series in the legend that can never be drawn.
  const quotaSeries = lowerIsBetter
    ? [achievedLabel, overLabel]
    : [achievedLabel, 'Still to go', overLabel]

  const quotaRows = groups.map(([key, value]) => {
    const target = progress[key]?.target ?? null
    const within = target === null ? value : Math.min(value, target)
    const over = target === null ? 0 : Math.max(value - target, 0)
    const left = target === null ? 0 : Math.max(target - value, 0)
    return lowerIsBetter ? [key, within, over] : [key, within, left, over]
  })

  return (
    <div className={`flex h-full flex-col ${groups.length ? '' : 'justify-center'}`}>
      <p className="text-3xl font-semibold tabular-nums text-ink-900">
        {formatValue(payload.value, payload.value_format, payload.unit)}
      </p>
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
            {payload.progress_percent?.toFixed(0) ?? '-'}% of {formatNumber(payload.target_value)}
          </p>
        </>
      )}
      {payload.computed_at && (
        <p className="mt-2 text-[11px] text-ink-400">
          Updated {relativeTime(payload.computed_at)}
        </p>
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
                      name: 'group',
                      label: payload.breakdown_variable || 'Group',
                      type: 'dimension',
                      data_type: 'text',
                    },
                    ...quotaSeries.map((label) => ({
                      name: label,
                      label,
                      type: 'measure' as const,
                      data_type: 'number' as const,
                    })),
                  ]
                : [
                    {
                      name: 'group',
                      label: payload.breakdown_variable || 'Group',
                      type: 'dimension',
                      data_type: 'text',
                    },
                    {
                      name: 'value',
                      label: payload.name ?? 'Value',
                      type: 'measure',
                      data_type: 'number',
                    },
                  ],
              rows: hasTargets ? quotaRows : groups.map(([key, value]) => [key, value]),
              row_count: groups.length,
              truncated: false,
              sql: '',
              duration_ms: 0,
            }}
            display={{
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
                  ? ['', STATUS_COLORS.critical]
                  : ['', '#e1e0d9', '#9ec5f4']
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
  )
}

function AddWidgetModal({
  dashboardId,
  projectId,
  page,
  onClose,
}: {
  dashboardId: string
  /** The dashboard's project, so the picker offers its charts and not every
   *  chart on the platform. Null is the shared area, which is its own place. */
  projectId: string | null
  /** The page being looked at, which is where a new widget belongs. */
  page: number
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<
    | 'chart'
    | 'indicator'
    | 'quality'
    | 'text'
    | 'countdown'
    | 'map'
    | 'html'
    | 'freshness'
  >('chart')
  const [datasetId, setDatasetId] = useState('')
  const [chartId, setChartId] = useState('')
  const [indicatorId, setIndicatorId] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [deadline, setDeadline] = useState('')
  const [deadlineLabel, setDeadlineLabel] = useState('')
  const [caption, setCaption] = useState('')
  const [showBreakdown, setShowBreakdown] = useState(true)
  const [latitude, setLatitude] = useState('')
  const [longitude, setLongitude] = useState('')
  const [measureAgg, setMeasureAgg] = useState('count')
  const [measureVariable, setMeasureVariable] = useState('')
  const [detail, setDetail] = useState<string[]>([])
  const [tiles, setTiles] = useState('')
  const [basemap, setBasemap] = useState('streets')
  const [html, setHtml] = useState('')
  const [freshnessDatasets, setFreshnessDatasets] = useState<string[]>([])

  // A dashboard about one round has no use for another round's charts, and a
  // list of everything is where the right one gets lost. A dashboard in the
  // shared area belongs to no project, so there is nothing to narrow to and it
  // goes on seeing everything the user can.
  const scope = projectId ? `&project_id=${projectId}` : ''
  const charts = useQuery({
    queryKey: ['charts', projectId],
    queryFn: () => api.get<Chart[]>(`/dashboards/charts?${scope.slice(1)}`),
  })
  const indicators = useQuery({
    queryKey: ['indicators', projectId],
    queryFn: () => api.get<Indicator[]>(`/monitoring/indicators?${scope.slice(1)}`),
  })
  const datasets = useQuery({
    queryKey: ['datasets', projectId],
    queryFn: () => api.get<Page<Dataset>>(`/datasets?limit=200${scope}`),
    enabled: kind === 'quality' || kind === 'map' || kind === 'freshness',
  })
  // The map needs the variables, to know which column holds the coordinates.
  const chosenDataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: kind === 'map' && Boolean(datasetId),
  })

  const add = useMutation({
    mutationFn: () =>
      api.post(`/dashboards/${dashboardId}/widgets`, {
        title:
          title ||
          (kind === 'chart'
            ? charts.data?.find((c) => c.id === chartId)?.name
            : kind === 'quality'
              ? `Data quality: ${datasets.data?.items.find((d) => d.id === datasetId)?.name ?? ''}`
              : kind === 'map'
                ? 'Interview locations'
                : kind === 'html'
                  ? 'Embedded content'
                  : kind === 'freshness'
                    ? 'Data freshness'
              : kind === 'countdown'
                ? deadlineLabel || 'Countdown'
                : indicators.data?.find((i) => i.id === indicatorId)?.name) ||
          'Widget',
        widget_type: kind,
        chart_id: kind === 'chart' ? chartId : null,
        indicator_id: kind === 'indicator' ? indicatorId : null,
        dataset_id: kind === 'quality' || kind === 'map' ? datasetId : null,
        page,
        config: {
          ...(kind === 'map'
            ? {
                latitude,
                longitude,
                measure_agg: measureAgg,
                measure_variable: measureAgg === 'count' ? '' : measureVariable,
                detail,
                ...(tiles.trim() ? { tiles: tiles.trim() } : {}),
                ...(basemap !== 'streets' ? { basemap } : {}),
              }
            : kind === 'freshness'
              ? { dataset_ids: freshnessDatasets, warn_hours: 24, critical_hours: 72 }
            : kind === 'html'
              ? { html }
            : kind === 'indicator'
              ? { show_breakdown: showBreakdown }
            : kind === 'text'
            ? { content }
            : kind === 'countdown'
              ? // A local datetime from the browser; sent as an instant so the
                // count reads the same wherever the dashboard is opened.
                { target: new Date(deadline).toISOString(), label: deadlineLabel }
              : {}),
          ...(caption.trim() ? { caption: caption.trim() } : {}),
        },
        layout:
          kind === 'map'
            ? { w: 6, h: 6 }
            : kind === 'freshness'
            ? { w: 4, h: 4 }
            : kind === 'countdown'
            ? { w: 3, h: 3 }
            : kind === 'indicator'
              ? // A tile with a chart under it needs the room for one.
                showBreakdown && chosenIndicator?.breakdown_variable
                ? { w: 4, h: 5 }
                : { w: 3, h: 3 }
              : { w: 6, h: 4 },
      }),
    onSuccess: () => {
      toast.push('Widget added', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', dashboardId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', dashboardId] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const chosenIndicator = indicators.data?.find((i) => i.id === indicatorId)
  const numericVariables = (chosenDataset.data?.variables ?? []).filter(
    (v) => v.var_type === 'numeric',
  )

  const canAdd =
    (kind === 'chart' && chartId) ||
    (kind === 'indicator' && indicatorId) ||
    (kind === 'quality' && datasetId) ||
    (kind === 'text' && content) ||
    (kind === 'countdown' && deadline && !Number.isNaN(Date.parse(deadline))) ||
    (kind === 'map' && datasetId && latitude && longitude) ||
    (kind === 'html' && html.trim()) ||
    (kind === 'freshness' && freshnessDatasets.length)

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
          <button className="btn-primary" onClick={() => add.mutate()} disabled={!canAdd}>
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
          <option value="chart">Saved chart or cross-tab</option>
          <option value="indicator">Indicator tile</option>
          <option value="quality">Data quality panel</option>
          <option value="text">Text note</option>
          <option value="countdown">Countdown to a date</option>
          <option value="map">Map of interview locations</option>
          <option value="html">Embedded HTML</option>
          <option value="freshness">How recent the data is</option>
        </select>
      </Field>

      {kind === 'chart' && (
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
                {chart.name} ({chart.chart_type === 'crosstab' ? 'cross-tab' : chart.chart_type})
              </option>
            ))}
          </select>
        </Field>
      )}

      {kind === 'quality' && (
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

      {kind === 'indicator' && (
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
            Show the breakdown by {chosenIndicator.breakdown_variable} under the number
          </label>
        )}
        </>
      )}

      {kind === 'map' && (
        <>
          <Field
            label="Dataset"
            hint="The one holding the GPS question - usually the interview level."
          >
            <select
              className="input"
              value={datasetId}
              onChange={(event) => {
                setDatasetId(event.target.value)
                setLatitude('')
                setLongitude('')
                setDetail([])
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
                  {measureAgg !== 'count' && (
                    <select
                      className="input"
                      value={measureVariable}
                      onChange={(event) => setMeasureVariable(event.target.value)}
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
                          disabled={!detail.includes(v.name) && detail.length >= 6}
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

      {kind === 'freshness' && (
        <FreshnessFields
          datasets={datasets.data?.items ?? []}
          config={{ dataset_ids: freshnessDatasets }}
          onChange={(patch) =>
            patch.dataset_ids && setFreshnessDatasets(patch.dataset_ids as string[])
          }
        />
      )}

      {kind === 'html' && (
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
            placeholder={'<h2>Round 3</h2>\n<p>Enumeration closes on Friday.</p>'}
          />
        </Field>
      )}

      {kind === 'countdown' && (
        <>
          <Field label="Counting down to" hint="Fieldwork closing, a reporting deadline.">
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

      {kind === 'text' && (
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

      <Field label="Title" hint="Leave blank to use the chart or indicator name">
        <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} />
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
  )
}

/**
 * Chooses which variables the dashboard offers as filters.
 *
 * The candidates come from the datasets the dashboard's own widgets use, since
 * a filter on a variable nothing here carries would do nothing. Only
 * categorical variables with a manageable number of values are offered: a
 * dropdown of 40,000 interview keys is not a filter.
 */
function FilterControlsModal({
  dashboardId,
  page,
  pageName,
  widgets,
  controls,
  onClose,
}: {
  dashboardId: string
  /** The page whose filters are being chosen; each page has its own. */
  page: number
  pageName: string
  /** This page's widgets - the candidates come from what is actually on it. */
  widgets: Widget[]
  /** Every control on the dashboard, so the other pages' are kept on save. */
  controls: FilterControl[]
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [chosen, setChosen] = useState<FilterControl[]>(() =>
    controlsForPage(controls, page),
  )

  const charts = useQuery({
    queryKey: ['charts'],
    queryFn: () => api.get<Chart[]>('/dashboards/charts'),
  })

  // A widget names either a chart (which names a dataset) or a dataset directly
  const datasetIds = useMemo(() => {
    const ids = new Set<string>()
    for (const widget of widgets) {
      if (widget.dataset_id) ids.add(widget.dataset_id)
      const chart = charts.data?.find((c) => c.id === widget.chart_id)
      if (chart) ids.add(chart.dataset_id)
    }
    return [...ids]
  }, [widgets, charts.data])

  const datasets = useDashboardDatasets(datasetIds)
  const details = useQuery({
    queryKey: ['dataset-details', datasetIds],
    queryFn: async () =>
      Promise.all(datasetIds.map((id) => api.get<Dataset>(`/datasets/${id}`))),
    enabled: datasetIds.length > 0,
  })

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
      toast.push('Filters saved', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', dashboardId] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const toggle = (control: FilterControl) => {
    const key = controlKey(control)
    const has = chosen.some((c) => controlKey(c) === key)
    setChosen(
      has ? chosen.filter((c) => controlKey(c) !== key) : [...chosen, control],
    )
  }

  /** Rename one control's label without disturbing which variable it filters. */
  const relabel = (control: FilterControl, label: string) => {
    const key = controlKey(control)
    setChosen(chosen.map((c) => (controlKey(c) === key ? { ...c, label } : c)))
  }

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
    const keys = new Set<string>()
    for (const dataset of details.data ?? []) {
      for (const variable of filterableVariables(dataset)) {
        keys.add(controlKey({ dataset_id: dataset.id, variable: variable.name }))
      }
    }
    return keys
  }, [details.data])

  const stranded = chosen.filter((control) => !offered.has(controlKey(control)))

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
            const options = filterableVariables(dataset)
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
            )
          })}
        </div>
      )}

      {stranded.length > 0 && (
        <div className="mt-4 rounded-card border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">
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
  )
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
function FilterChoice({
  variable,
  datasetId,
  chosen,
  onToggle,
  onRelabel,
}: {
  variable: { name: string; label?: string; n_unique: number }
  datasetId: string
  chosen: FilterControl[]
  onToggle: (control: FilterControl) => void
  onRelabel: (control: FilterControl, label: string) => void
}) {
  const control: FilterControl = {
    variable: variable.name,
    dataset_id: datasetId,
    label: variable.label || variable.name,
  }
  const key = controlKey(control)
  const picked = chosen.find((c) => controlKey(c) === key)

  return (
    <div className="flex items-center gap-2 text-sm text-ink-700">
      <label className="flex min-w-0 flex-1 items-center gap-2">
        <input type="checkbox" checked={Boolean(picked)} onChange={() => onToggle(control)} />
        <span className="truncate">
          {variable.label ? `${variable.name} - ${variable.label}` : variable.name}
          <span className="text-ink-400"> ({variable.n_unique})</span>
        </span>
      </label>
      {picked && (
        <input
          className="input h-7 w-36 shrink-0 py-0 text-xs"
          aria-label={`Label for the ${variable.name} filter`}
          title="What this filter is called on the dashboard"
          value={picked.label ?? ''}
          placeholder={variable.name}
          onChange={(event) => onRelabel(control, event.target.value)}
        />
      )}
    </div>
  )
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
function EditWidgetModal({
  dashboardId,
  projectId,
  widget,
  pageNames,
  dashboardOpacity,
  onClose,
}: {
  dashboardId: string
  /** The dashboard's project: the same set of charts the picker offered. */
  projectId: string | null
  widget: Widget
  pageNames: string[]
  /** What this widget's transparency falls back to when it sets none. */
  dashboardOpacity: number
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(widget.title ?? '')
  const [page, setPage] = useState(widget.page ?? 0)
  const [width, setWidth] = useState(Number(widget.layout?.w ?? 6))
  const [height, setHeight] = useState(Number(widget.layout?.h ?? 4))
  const [config, setConfig] = useState<Record<string, any>>({ ...(widget.config ?? {}) })
  const [chartId, setChartId] = useState(widget.chart_id ?? '')
  const [indicatorId, setIndicatorId] = useState(widget.indicator_id ?? '')
  const [datasetId, setDatasetId] = useState(widget.dataset_id ?? '')

  const kind = widget.widget_type
  const set = (patch: Record<string, any>) => setConfig({ ...config, ...patch })

  const charts = useQuery({
    queryKey: ['charts', projectId],
    queryFn: () =>
      api.get<Chart[]>(
        `/dashboards/charts${projectId ? `?project_id=${projectId}` : ''}`,
      ),
    enabled: kind === 'chart',
  })
  const indicators = useQuery({
    queryKey: ['indicators', projectId],
    queryFn: () =>
      api.get<Indicator[]>(
        `/monitoring/indicators${projectId ? `?project_id=${projectId}` : ''}`,
      ),
    enabled: kind === 'indicator',
  })
  const datasets = useQuery({
    queryKey: ['datasets', projectId],
    queryFn: () =>
      api.get<Page<Dataset>>(
        `/datasets?limit=200${projectId ? `&project_id=${projectId}` : ''}`,
      ),
    enabled: kind === 'quality' || kind === 'map' || kind === 'freshness',
  })
  const mapDataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: kind === 'map' && Boolean(datasetId),
  })
  const boundaries = useQuery({
    queryKey: ['boundaries', projectId],
    queryFn: () =>
      api.get<BoundaryLayer[]>(
        `/boundaries${projectId ? `?project_id=${projectId}` : ''}`,
      ),
    enabled: kind === 'map',
  })
  // The attributes of whichever layer is chosen, so the two dropdowns below
  // offer its own column names rather than asking anyone to type them.
  const boundaryProperties =
    boundaries.data?.find((item) => item.id === config.boundary_id)?.properties ?? []

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
          ...(kind === 'map' || kind === 'quality' ? { dataset_id: datasetId } : {}),
        },
        // Sent whole, so a resize here lands the same way a drag does.
        layout: { ...(widget.layout ?? {}), w: width, h: height },
        ...(kind === 'chart' ? { chart_id: chartId || null } : {}),
        ...(kind === 'indicator' ? { indicator_id: indicatorId || null } : {}),
        ...(kind === 'quality' || kind === 'map' ? { dataset_id: datasetId || null } : {}),
      }),
    onSuccess: () => {
      toast.push('Widget updated', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', dashboardId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', dashboardId] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const numericVariables = (mapDataset.data?.variables ?? []).filter(
    (v) => v.var_type === 'numeric',
  )

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
          value={config.caption ?? ''}
          placeholder="Completed interviews only. Excludes the pilot round."
          onChange={(event) => set({ caption: event.target.value || undefined })}
        />
      </Field>

      <Field
        label="Background"
        hint="This widget's own colour. The dashboard's transparency still applies to it."
      >
        <ColorPicker
          value={config.background ?? ''}
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
            onChange={(event) => set({ opacity: Number(event.target.value) / 100 })}
          />
          <span className="w-12 text-sm text-ink-600">
            {Math.round((config.opacity ?? dashboardOpacity) * 100)}%
          </span>
          {config.opacity !== undefined && (
            <button className="btn-ghost btn-sm" onClick={() => set({ opacity: undefined })}>
              Follow dashboard
            </button>
          )}
        </div>
      </Field>

      <Field label="Font">
        <select
          className="input"
          aria-label="Widget font"
          value={config.font_family ?? ''}
          onChange={(event) => set({ font_family: event.target.value || undefined })}
        >
          {WIDGET_FONTS.map((font) => (
            <option key={font.label} value={font.value}>
              {font.label}
            </option>
          ))}
        </select>
      </Field>

      <Field
        label="Text colour"
        hint="The title, the caption, and the labels on the chart: its axes, its legend and the values beside its marks."
      >
        <ColorPicker
          value={config.font_color ?? ''}
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
          value={config.title_font ?? ''}
          onChange={(event) => set({ title_font: event.target.value || undefined })}
        >
          {TITLE_FONTS.map((font) => (
            <option key={font.label} value={font.value}>
              {font.label}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Title position">
        <select
          className="input"
          aria-label="Widget title position"
          value={config.title_align ?? 'left'}
          onChange={(event) =>
            set({
              title_align:
                event.target.value === 'left'
                  ? undefined
                  : (event.target.value as 'center' | 'right'),
            })
          }
        >
          <option value="left">Left</option>
          <option value="center">Centred</option>
          <option value="right">Right</option>
        </select>
      </Field>

      <Field label="Shadow" hint="Lifts this widget off the dashboard behind it.">
        <select
          className="input"
          aria-label="Widget shadow"
          value={config.shadow ?? 'none'}
          onChange={(event) =>
            set({
              shadow:
                event.target.value === 'none'
                  ? undefined
                  : (event.target.value as 'soft' | 'strong'),
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
            onChange={(event) => set({ title_size: Number(event.target.value) })}
          />
          <span className="w-12 text-sm text-ink-600">
            {config.title_size ?? DEFAULT_TITLE_SIZE}px
          </span>
          {config.title_size !== undefined && (
            <button className="btn-ghost btn-sm" onClick={() => set({ title_size: undefined })}>
              Default
            </button>
          )}
        </div>
      </Field>

      {kind === 'chart' && (
        <Field
          label="Chart colour"
          hint="The colour this chart leads with. A chart with several series keeps distinct hues behind it, so they stay tellable apart."
        >
          <ColorPicker
            value={config.series_color ?? ''}
            onChange={(next) => set({ series_color: next || undefined })}
            allowNone
            label="Chart series"
            noneLabel="Use the dashboard's theme"
          />
        </Field>
      )}

      {kind === 'chart' && (
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

          <Field
            label="Chart text size"
            hint="The axes, the legend and the printed values together. Bigger for a board read across a room, smaller for a crowded tile."
          >
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={8}
                max={28}
                step={1}
                className="w-40"
                aria-label="Chart text size"
                value={config.chart_font_size ?? DEFAULT_CHART_TEXT}
                onChange={(event) => set({ chart_font_size: Number(event.target.value) })}
              />
              <span className="w-12 text-sm text-ink-600">
                {config.chart_font_size ?? DEFAULT_CHART_TEXT}px
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
        </>
      )}

      {kind === 'chart' && (
        <Field label="Chart">
          <select
            className="input"
            value={chartId}
            onChange={(event) => setChartId(event.target.value)}
          >
            {charts.data?.map((chart) => (
              <option key={chart.id} value={chart.id}>
                {chart.name} ({chart.chart_type === 'crosstab' ? 'cross-tab' : chart.chart_type})
              </option>
            ))}
          </select>
        </Field>
      )}

      {kind === 'indicator' && (
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
              onChange={(event) => set({ show_breakdown: event.target.checked })}
            />
            Show the breakdown chart under the number
          </label>
        </>
      )}

      {(kind === 'quality' || kind === 'map') && (
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

      {kind === 'map' && (
        <>
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="Latitude">
              <select
                className="input"
                value={config.latitude ?? ''}
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
                value={config.longitude ?? ''}
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
          <Field label="What each pin counts">
            <div className="flex gap-2">
              <select
                className="input w-56"
                value={config.measure_agg ?? 'count'}
                onChange={(event) => set({ measure_agg: event.target.value })}
              >
                <option value="count">How many records</option>
                <option value="sum">Total of</option>
                <option value="mean">Average of</option>
                <option value="max">Highest</option>
                <option value="min">Lowest</option>
              </select>
              {(config.measure_agg ?? 'count') !== 'count' && (
                <select
                  className="input"
                  value={config.measure_variable ?? ''}
                  onChange={(event) => set({ measure_variable: event.target.value })}
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
          <Field
            label="Point shape"
            hint="A shape is told apart in a photocopy; a shade of a colour is not."
          >
            <select
              className="input"
              aria-label="Map point shape"
              value={config.point_icon ?? 'circle'}
              onChange={(event) =>
                set({
                  point_icon:
                    event.target.value === 'circle' ? undefined : event.target.value,
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
                value={config.point_color ?? ''}
                onChange={(next) => set({ point_color: next || undefined })}
                allowNone
                label="Map point"
                noneLabel="Default blue"
              />
            </Field>
            <Field label="Point size" hint="How big a pin is before the value scales it.">
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={6}
                  max={40}
                  step={1}
                  className="w-40"
                  aria-label="Map point size"
                  value={config.point_size ?? DEFAULT_POINT_SIZE}
                  onChange={(event) => set({ point_size: Number(event.target.value) })}
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
                value={Math.round((config.point_opacity ?? DEFAULT_POINT_OPACITY) * 100)}
                onChange={(event) => set({ point_opacity: Number(event.target.value) / 100 })}
              />
              <span className="w-12 text-sm text-ink-600">
                {Math.round((config.point_opacity ?? DEFAULT_POINT_OPACITY) * 100)}%
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

          <Field label="Base map" hint="A reader can switch this on the map itself.">
            <select
              className="input"
              value={config.basemap ?? 'streets'}
              onChange={(event) =>
                set({ basemap: event.target.value === 'streets' ? undefined : event.target.value })
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
              value={config.tiles ?? ''}
              placeholder={DEFAULT_TILES}
              onChange={(event) => set({ tiles: event.target.value })}
            />
          </Field>

          <Field
            label="Boundaries"
            hint="Enumeration areas, districts or villages, drawn under the pins."
          >
            <select
              className="input"
              aria-label="Boundary layer"
              value={config.boundary_id ?? ''}
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
              <Field label="Write on each area" hint="Which attribute names it on the map.">
                <select
                  className="input"
                  aria-label="Boundary label attribute"
                  value={config.boundary_label ?? ''}
                  onChange={(event) => set({ boundary_label: event.target.value || undefined })}
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
                    value={config.area_variable ?? ''}
                    onChange={(event) => set({ area_variable: event.target.value || undefined })}
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
                <Field label="Matched against" hint="The area code on the boundary layer.">
                  <select
                    className="input"
                    aria-label="Boundary code attribute"
                    value={config.boundary_key ?? ''}
                    onChange={(event) => set({ boundary_key: event.target.value || undefined })}
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
                  Choose the boundary attribute the recorded area should match, or every
                  record will be reported as a mismatch.
                </p>
              )}
            </>
          )}
        </>
      )}

      {kind === 'text' && (
        <Field label="Text">
          <textarea
            className="input"
            rows={4}
            value={config.content ?? ''}
            onChange={(event) => set({ content: event.target.value })}
          />
        </Field>
      )}

      {kind === 'html' && (
        <Field label="HTML" hint="Rendered in a sandboxed frame.">
          <HtmlLibrary
            html={config.html ?? ''}
            projectId={projectId}
            onLoad={(next) => set({ html: next })}
          />
          <textarea
            className="input font-mono text-xs"
            rows={8}
            value={config.html ?? ''}
            onChange={(event) => set({ html: event.target.value })}
          />
        </Field>
      )}

      {kind === 'countdown' && (
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
                    : '',
                })
              }
            />
          </Field>
          <Field label="Caption">
            <input
              className="input"
              value={config.label ?? ''}
              onChange={(event) => set({ label: event.target.value })}
            />
          </Field>
          <Field label="When it runs out">
            <input
              className="input"
              value={config.expired_text ?? ''}
              placeholder="Time is up"
              onChange={(event) => set({ expired_text: event.target.value })}
            />
          </Field>
        </>
      )}

      {kind === 'freshness' && (
        <FreshnessFields
          datasets={datasets.data?.items ?? []}
          config={config}
          onChange={set}
        />
      )}
    </Modal>
  )
}

/** An ISO instant as the value a datetime-local input wants. */
function toLocalInput(iso: unknown): string {
  if (!iso || typeof iso !== 'string') return ''
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}T${pad(
    when.getHours(),
  )}:${pad(when.getMinutes())}`
}

/** Which datasets the freshness widget watches, and when to call them stale. */
function FreshnessFields({
  datasets,
  config,
  onChange,
}: {
  datasets: Dataset[]
  config: Record<string, any>
  onChange: (patch: Record<string, any>) => void
}) {
  const chosen: string[] = config.dataset_ids ?? []
  const toggle = (id: string) =>
    onChange({
      dataset_ids: chosen.includes(id)
        ? chosen.filter((existing) => existing !== id)
        : [...chosen, id],
    })

  return (
    <>
      <Field label="Datasets to watch" hint="Each gets a line saying how recent it is.">
        <div className="grid max-h-52 gap-1 overflow-auto sm:grid-cols-2">
          {datasets.map((dataset) => (
            <label key={dataset.id} className="flex items-center gap-2 text-sm text-ink-700">
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
            onChange={(event) => onChange({ warn_hours: Number(event.target.value) || 24 })}
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
  )
}


/** The public link, and the name it can also answer on.
 *
 *  A token URL is unguessable, which is what makes it safe to paste to one
 *  person. A hostname is the opposite by design - it is meant to be typed from
 *  memory - so the two sit together here and the difference is stated rather
 *  than left to be discovered.
 */
function PublicLinkBar({
  dashboard,
  canEdit,
}: {
  dashboard: Dashboard
  canEdit: boolean
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [naming, setNaming] = useState(false)
  const [label, setLabel] = useState('')

  const info = useQuery({
    queryKey: ['platform-info'],
    queryFn: () => api.get<{ dashboard_domain: string }>('/system/info'),
    staleTime: 5 * 60 * 1000,
  })
  const domain = info.data?.dashboard_domain ?? ''

  const save = useMutation({
    mutationFn: (hostname: string) =>
      api.put<Dashboard>(`/dashboards/${dashboard.id}/hostname`, { hostname }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', dashboard.id] })
      setNaming(false)
      setLabel('')
      toast.push(
        updated.public_hostname
          ? `This dashboard now answers on ${updated.public_hostname}`
          : 'The name was removed',
        'success',
      )
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <div className="mb-4 rounded-card border border-brand-200 bg-brand-50 px-4 py-2.5 text-sm text-brand-800">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="info" icon="⇗">
          Public
        </Badge>
        <span>Anyone with this link can view the dashboard:</span>
        <code className="rounded bg-white px-2 py-0.5 text-xs">
          {location.origin}/shared/{dashboard.public_token}
        </code>
      </div>

      {dashboard.public_hostname && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span>It also answers on:</span>
          <a
            className="rounded bg-white px-2 py-0.5 font-mono text-xs"
            href={`https://${dashboard.public_hostname}`}
            target="_blank"
            rel="noreferrer"
          >
            {dashboard.public_hostname}
          </a>
          {canEdit && (
            <button
              className="btn-ghost btn-sm text-red-600"
              onClick={() => save.mutate('')}
              disabled={save.isPending}
            >
              Remove the name
            </button>
          )}
        </div>
      )}

      {canEdit && !dashboard.public_hostname && domain && !naming && (
        <button className="btn-ghost btn-sm mt-1" onClick={() => setNaming(true)}>
          Give it a name…
        </button>
      )}

      {canEdit && naming && domain && (
        <div className="mt-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <input
              className="input w-56 py-1 text-xs"
              placeholder="labour-force"
              value={label}
              autoFocus
              onChange={(event) => setLabel(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && label.trim()) save.mutate(label.trim())
                if (event.key === 'Escape') setNaming(false)
              }}
            />
            <span className="font-mono text-xs">.{domain}</span>
            <button
              className="btn-primary btn-sm"
              onClick={() => save.mutate(label.trim())}
              disabled={!label.trim() || save.isPending}
            >
              Assign
            </button>
            <button className="btn-ghost btn-sm" onClick={() => setNaming(false)}>
              Cancel
            </button>
          </div>
          <p className="mt-1.5 text-xs text-brand-800/80">
            A name is meant to be typed from memory, so it is not a secret the way
            the link above is: anyone who guesses it reaches this dashboard.
          </p>
        </div>
      )}
    </div>
  )
}

/**
 * The door in front of a password-protected shared link.
 *
 * The password is traded once for a grant that the other routes accept, rather
 * than sent with every request: the hash behind it is deliberately slow, and a
 * dashboard on an office wall refreshing every minute would otherwise spend
 * its life being hashed.
 */
function SharePasswordPrompt({
  token,
  onUnlocked,
}: {
  token: string
  onUnlocked: () => void
}) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { grant } = await api.post<{ grant: string }>(
        `/public/dashboards/${token}/unlock`,
        { password },
      )
      shareGrants.set(token, grant)
      onUnlocked()
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-sm py-16">
      <Card>
        <h1 className="text-base font-semibold text-ink-800">This dashboard is protected</h1>
        <p className="mt-1 text-sm text-ink-600">
          Enter the password you were given with the link.
        </p>
        <form className="mt-4" onSubmit={submit}>
          <Field label="Password">
            <input
              className="input"
              type="password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
          <button className="btn-primary w-full" type="submit" disabled={busy || !password}>
            {busy ? 'Checking…' : 'Open dashboard'}
          </button>
        </form>
      </Card>
    </div>
  )
}
