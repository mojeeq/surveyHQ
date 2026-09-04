import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import GridLayout, { type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { CHART_THEMES, STATUS_COLORS } from '@/lib/charts'
import { formatNumber, formatValue, relativeTime } from '@/lib/format'
import type {
  Appearance,
  Chart,
  Dashboard,
  Dataset,
  Indicator,
  Page,
  Widget,
} from '@/lib/types'
import AssignProject from '@/components/AssignProject'
import ChartCard from '@/components/ChartCard'
import DashboardFilters, {
  controlsForPage,
  filterableVariables,
  toFilterGroup,
  useDashboardDatasets,
  type FilterControl,
} from '@/components/DashboardFilters'
import CrosstabTable from '@/components/CrosstabTable'
import ErrorBoundary from '@/components/ErrorBoundary'
import MapWidget, { DEFAULT_TILES } from '@/components/MapWidget'
import AppearanceModal, {
  canvasStyle,
  isDark,
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
const ROW_HEIGHT = 74
// Breathing room inside the canvas, so a widget dragged to the far right stops
// short of the edge instead of butting against it.
const CANVAS_PADDING = 16

const appearanceOf = (dashboard: Dashboard | undefined): Appearance =>
  (dashboard?.appearance ?? {}) as Appearance

export default function DashboardView({ publicToken }: { publicToken?: string }) {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [activePage, setActivePage] = useState(0)
  const [filterValues, setFilterValues] = useState<Record<string, string>>({})
  const [editingFilters, setEditingFilters] = useState(false)
  const [editingStyle, setEditingStyle] = useState(false)
  const [editingWidget, setEditingWidget] = useState<Widget | null>(null)
  const [width, setWidth] = useState(1200)

  const isPublic = Boolean(publicToken)
  const basePath = isPublic ? `/public/dashboards/${publicToken}` : `/dashboards/${id}`

  const dashboard = useQuery({
    queryKey: ['dashboard', id, publicToken],
    queryFn: () => api.get<Dashboard>(basePath),
  })

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

  const rendered = useQuery({
    // The values are part of the key, so changing a filter refetches rather
    // than showing the previous selection's numbers under the new label. So is
    // the page, whose filters are its own.
    queryKey: ['dashboard-data', id, publicToken, activePage, filterValues],
    queryFn: () =>
      api.post<{ widgets: Record<string, any> }>(
        `${basePath}/data`,
        toFilterGroup(pageControls, filterValues),
      ),
    enabled: Boolean(dashboard.data),
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
        navigator.clipboard?.writeText(url).catch(() => undefined)
        toast.push('Public link copied to your clipboard', 'success')
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
                    onClick={() => share.mutate(!dashboard.data!.is_public)}
                  >
                    {dashboard.data!.is_public ? 'Stop sharing' : 'Share link'}
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

      {/* Everything the dashboard is read for sits on the canvas: the filters
          in use, the pages, and the widgets. The page header stays off it, so
          the toolbar's buttons keep the contrast they were designed with. */}
      <div
        className={canvas ? 'rounded-card p-4' : ''}
        style={canvas}
        data-testid="dashboard-canvas"
      >
      <DashboardFilters
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
        onSelect={setActivePage}
        onChange={(next) => savePages.mutate(next)}
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
          ref={(node) => node && setWidth(node.clientWidth)}
          className={fixedWidth > width ? 'overflow-x-auto' : ''}
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
              // Let the dashboard's own background through the card. The charts
              // inside draw on a transparent canvas, so they come with it.
              style={
                widgetOpacity < 1
                  ? { backgroundColor: `rgba(255,255,255,${widgetOpacity})` }
                  : undefined
              }
            >
              <ErrorBoundary what={`"${widget.title || 'this widget'}"`}>
              <WidgetFrame
                widget={widget}
                payload={rendered.data?.widgets[widget.id]}
                loading={rendered.isLoading}
                editing={editing && !isPublic}
                canEdit={!isPublic && can('analyst')}
                theme={dashboard.data!.theme ?? 'default'}
                pageNames={pageNames}
                onMove={(toPage) => moveWidget.mutate({ widgetId: widget.id, page: toPage })}
                onEdit={() => setEditingWidget(widget)}
                onRemove={() => {
                  if (confirm(`Remove "${widget.title || 'this widget'}" from the dashboard?`))
                    removeWidget.mutate(widget.id)
                }}
              />
              </ErrorBoundary>
            </div>
          ))}
        </GridLayout>
        </div>
      )}
      </div>

      {adding && (
        <AddWidgetModal dashboardId={id} page={page} onClose={() => setAdding(false)} />
      )}
      {editingWidget && (
        <EditWidgetModal
          dashboardId={id}
          widget={editingWidget}
          pageNames={pageNames}
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

function WidgetFrame({
  widget,
  payload,
  loading,
  editing,
  canEdit,
  theme,
  pageNames,
  onMove,
  onEdit,
  onRemove,
}: {
  widget: Widget
  payload: any
  loading: boolean
  editing: boolean
  canEdit: boolean
  /** The dashboard's categorical ordering, applied to every chart on it. */
  theme: string
  /** Every page on this dashboard, so a widget can be sent to another one. */
  pageNames: string[]
  onMove: (page: number) => void
  onEdit: () => void
  onRemove: () => void
}) {
  return (
    <div className="flex h-full flex-col">
      <header className="widget-handle group flex shrink-0 items-center justify-between gap-2 border-b border-ink-200 px-4 py-2.5">
        <h3 className={`truncate text-sm font-semibold text-ink-800 ${editing ? 'cursor-move' : ''}`}>
          {widget.title || payload?.name || 'Widget'}
        </h3>
        <div className="flex shrink-0 items-center gap-1">
        {canEdit && pageNames.length > 1 && (
          // Which page a widget belongs on is usually decided after it is
          // built, and rebuilding it somewhere else is not an answer.
          <select
            className={`h-7 rounded border border-ink-200 bg-white px-1.5 text-xs text-ink-600 transition-opacity ${
              editing ? 'opacity-100' : 'opacity-0 focus:opacity-100 group-hover:opacity-100'
            }`}
            title="Move this widget to another page"
            aria-label={`Move ${widget.title || 'widget'} to another page`}
            value={widget.page ?? 0}
            onChange={(event) => onMove(Number(event.target.value))}
          >
            {pageNames.map((name, index) => (
              <option key={index} value={index}>
                {name}
              </option>
            ))}
          </select>
        )}
        {canEdit && (
          <button
            className={`btn-ghost btn-sm shrink-0 text-ink-500 transition-opacity ${
              editing ? 'opacity-100' : 'opacity-0 focus:opacity-100 group-hover:opacity-100'
            }`}
            onClick={onEdit}
            title="Edit this widget"
            aria-label={`Edit ${widget.title || 'widget'}`}
          >
            ✎
          </button>
        )}
        {canEdit && (
          // Removal used to live only inside Arrange mode with nothing saying
          // so, which read as "widgets cannot be removed". It is now always
          // reachable: visible on hover, and permanently while arranging.
          <button
            className={`btn-ghost btn-sm shrink-0 text-red-600 transition-opacity ${
              editing ? 'opacity-100' : 'opacity-0 focus:opacity-100 group-hover:opacity-100'
            }`}
            onClick={onRemove}
            title="Remove this widget"
            aria-label={`Remove ${widget.title || 'widget'}`}
          >
            ✕
          </button>
        )}
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col overflow-auto p-4">
        {/* A filter the widget's dataset has no column for is dropped rather
            than failing the query - which otherwise looks like a broken
            filter, since the widget goes on showing every row in silence. */}
        {payload?.filters_ignored?.length > 0 && (
          <p className="mb-2 shrink-0 text-[11px] text-amber-700">
            Not filtered by {payload.filters_ignored.join(', ')} — this widget's
            dataset does not have {payload.filters_ignored.length > 1 ? 'those' : 'that'}{' '}
            {payload.filters_ignored.length > 1 ? 'variables' : 'variable'}.
          </p>
        )}
        {loading ? (
          <Loading />
        ) : !payload ? (
          <p className="py-6 text-center text-sm text-ink-400">No data</p>
        ) : payload.error ? (
          <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {payload.error}
          </p>
        ) : payload.type === 'indicator' ? (
          <IndicatorWidget payload={payload} theme={theme} />
        ) : payload.type === 'quality' ? (
          <QualityWidget payload={payload} />
        ) : payload.type === 'crosstab' ? (
          <CrosstabTable result={payload.result} compact fill />
        ) : payload.type === 'freshness' ? (
          <FreshnessWidget payload={payload} />
        ) : payload.type === 'map' ? (
          <MapWidget
            points={payload.points ?? []}
            detail={payload.detail ?? []}
            measure={payload.measure}
            tiles={widget.config?.tiles as string | undefined}
            truncated={payload.truncated}
          />
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
            display={payload.display}
          />
        ) : null}
      </div>
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
  onSelect,
  onChange,
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
  onSelect: (index: number) => void
  onChange: (pages: { name: string }[]) => void
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
    onChange(named.filter((_, i) => i !== index))
    onSelect(Math.max(0, index - 1))
  }

  if (count <= 1 && !canEdit) return null

  return (
    <div
      className={`mb-4 flex flex-wrap items-center gap-1 border-b ${
        onDark ? 'border-white/25' : 'border-ink-200'
      } ${band ? 'rounded-t-lg px-2' : ''}`}
      style={band ? { backgroundColor: band } : undefined}
    >
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
          >
            {page.name}
          </button>
        ))}
      {canEdit && (
        <>
          <button
            className={`btn-ghost btn-sm ${onDark ? 'text-white/80' : 'text-ink-500'}`}
            onClick={addPage}
          >
            + Page
          </button>
          {/* Renaming used to be a double-click on the tab and nothing said so,
              which is no way to find a feature. */}
          <button
            className={`btn-ghost btn-sm ${onDark ? 'text-white/80' : 'text-ink-500'}`}
            onClick={() => renamePage(active)}
          >
            Rename
          </button>
          {count > 1 && (
            <button
              className="btn-ghost btn-sm text-red-600"
              onClick={() => removePage(active)}
            >
              Delete page
            </button>
          )}
        </>
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
            </li>
          ))}
          {!failing.length && (
            <li className="text-sm text-ink-500">
              Every active check on {payload.name} passed.
            </li>
          )}
        </ul>
      )}

      {stale && (
        <p className="mt-2 text-[11px] text-ink-400">
          {/* Results are shown as last run, not recomputed on open, so say when. */}
          Oldest result {relativeTime(stale)}
        </p>
      )}
    </div>
  )
}

function IndicatorWidget({ payload, theme }: { payload: any; theme: string }) {
  const color = STATUS_COLORS[payload.status as keyof typeof STATUS_COLORS] ?? STATUS_COLORS.unknown
  const breakdown: Record<string, number> = payload.breakdown ?? {}
  const groups = Object.entries(breakdown)

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
            {payload.progress_percent?.toFixed(0) ?? '–'}% of {formatNumber(payload.target_value)}
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
              columns: [
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
              rows: groups.map(([key, value]) => [key, value]),
              row_count: groups.length,
              truncated: false,
              sql: '',
              duration_ms: 0,
            }}
          />
        </div>
      )}
    </div>
  )
}

function AddWidgetModal({
  dashboardId,
  page,
  onClose,
}: {
  dashboardId: string
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
  const [showBreakdown, setShowBreakdown] = useState(true)
  const [latitude, setLatitude] = useState('')
  const [longitude, setLongitude] = useState('')
  const [measureAgg, setMeasureAgg] = useState('count')
  const [measureVariable, setMeasureVariable] = useState('')
  const [detail, setDetail] = useState<string[]>([])
  const [tiles, setTiles] = useState('')
  const [html, setHtml] = useState('')
  const [freshnessDatasets, setFreshnessDatasets] = useState<string[]>([])

  const charts = useQuery({ queryKey: ['charts'], queryFn: () => api.get<Chart[]>('/dashboards/charts') })
  const indicators = useQuery({
    queryKey: ['indicators'],
    queryFn: () => api.get<Indicator[]>('/monitoring/indicators'),
  })
  const datasets = useQuery({
    queryKey: ['datasets'],
    queryFn: () => api.get<Page<Dataset>>('/datasets?limit=200'),
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
        config:
          kind === 'map'
            ? {
                latitude,
                longitude,
                measure_agg: measureAgg,
                measure_variable: measureAgg === 'count' ? '' : measureVariable,
                detail,
                ...(tiles.trim() ? { tiles: tiles.trim() } : {}),
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
              : {},
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
                        {v.label ? `${v.name} — ${v.label}` : v.name}
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
                        {v.label ? `${v.name} — ${v.label}` : v.name}
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
                          {v.label ? `${v.name} — ${v.label}` : v.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              </Field>

              <Field
                label="Map tiles"
                hint="Leave blank for OpenStreetMap. A server with no internet can point this at its own tile service."
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
    const has = chosen.some((c) => c.variable === control.variable)
    setChosen(
      has
        ? chosen.filter((c) => c.variable !== control.variable)
        : [...chosen, control],
    )
  }

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
        any widget it could not reach — the variables below are the ones this
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
                      <label
                        key={variable.name}
                        className="flex items-center gap-2 text-sm text-ink-700"
                      >
                        <input
                          type="checkbox"
                          checked={chosen.some((c) => c.variable === variable.name)}
                          onChange={() =>
                            toggle({
                              variable: variable.name,
                              dataset_id: dataset.id,
                              label: variable.label || variable.name,
                            })
                          }
                        />
                        <span className="truncate">
                          {variable.label
                            ? `${variable.name} — ${variable.label}`
                            : variable.name}
                          <span className="text-ink-400"> ({variable.n_unique})</span>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </Modal>
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
  widget,
  pageNames,
  onClose,
}: {
  dashboardId: string
  widget: Widget
  pageNames: string[]
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
    queryKey: ['charts'],
    queryFn: () => api.get<Chart[]>('/dashboards/charts'),
    enabled: kind === 'chart',
  })
  const indicators = useQuery({
    queryKey: ['indicators'],
    queryFn: () => api.get<Indicator[]>('/monitoring/indicators'),
    enabled: kind === 'indicator',
  })
  const datasets = useQuery({
    queryKey: ['datasets'],
    queryFn: () => api.get<Page<Dataset>>('/datasets?limit=200'),
    enabled: kind === 'quality' || kind === 'map' || kind === 'freshness',
  })
  const mapDataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: kind === 'map' && Boolean(datasetId),
  })

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/dashboards/${dashboardId}/widgets/${widget.id}`, {
        title,
        page,
        config: {
          ...config,
          ...(kind === 'map' || kind === 'quality' ? { dataset_id: datasetId } : {}),
        },
        // Sent whole, so a resize here lands the same way a drag does.
        layout: { ...(widget.layout ?? {}), w: width, h: height },
      }),
    onSuccess: () => {
      toast.push('Widget updated', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', dashboardId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', dashboardId] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  // The pieces a widget references live on the widget row rather than in its
  // config, so they are saved separately - the same PATCH the board uses.
  const saveReferences = useMutation({
    mutationFn: () =>
      api.patch(`/dashboards/${dashboardId}`, {
        widgets: [
          {
            id: widget.id,
            title,
            widget_type: widget.widget_type,
            chart_id: kind === 'chart' ? chartId || null : widget.chart_id,
            indicator_id: kind === 'indicator' ? indicatorId || null : widget.indicator_id,
            dataset_id:
              kind === 'quality' || kind === 'map' ? datasetId || null : widget.dataset_id,
            config,
            layout: { ...(widget.layout ?? {}), w: width, h: height },
            position: widget.position,
            page,
          },
        ],
      }),
  })

  const numericVariables = (mapDataset.data?.variables ?? []).filter(
    (v) => v.var_type === 'numeric',
  )

  const referencesChanged =
    (kind === 'chart' && chartId !== (widget.chart_id ?? '')) ||
    (kind === 'indicator' && indicatorId !== (widget.indicator_id ?? '')) ||
    ((kind === 'quality' || kind === 'map') && datasetId !== (widget.dataset_id ?? ''))

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
            onClick={async () => {
              // The whole-dashboard PATCH would drop the other pages' widgets
              // if it were the only call, so it runs only when something it
              // alone can change actually changed.
              if (referencesChanged) await saveReferences.mutateAsync()
              save.mutate()
            }}
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
          <Field label="Map tiles" hint="Blank uses OpenStreetMap.">
            <input
              className="input font-mono text-xs"
              value={config.tiles ?? ''}
              placeholder={DEFAULT_TILES}
              onChange={(event) => set({ tiles: event.target.value })}
            />
          </Field>
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
