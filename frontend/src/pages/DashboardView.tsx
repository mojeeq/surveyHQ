import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import GridLayout, { type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { CHART_THEMES, STATUS_COLORS } from '@/lib/charts'
import { formatNumber, formatValue, relativeTime } from '@/lib/format'
import type { Chart, Dashboard, Dataset, Indicator, Page, Widget } from '@/lib/types'
import AssignProject from '@/components/AssignProject'
import ChartCard from '@/components/ChartCard'
import DashboardFilters, {
  filterableVariables,
  toFilterGroup,
  useDashboardDatasets,
  type FilterControl,
} from '@/components/DashboardFilters'
import CrosstabTable from '@/components/CrosstabTable'
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
  const [width, setWidth] = useState(1200)

  const isPublic = Boolean(publicToken)
  const basePath = isPublic ? `/public/dashboards/${publicToken}` : `/dashboards/${id}`

  const dashboard = useQuery({
    queryKey: ['dashboard', id, publicToken],
    queryFn: () => api.get<Dashboard>(basePath),
  })

  const filterControls: FilterControl[] = (dashboard.data?.filters ??
    []) as unknown as FilterControl[]

  const rendered = useQuery({
    // The values are part of the key, so changing a filter refetches rather
    // than showing the previous selection's numbers under the new label.
    queryKey: ['dashboard-data', id, publicToken, filterValues],
    queryFn: () =>
      api.post<{ widgets: Record<string, any> }>(
        `${basePath}/data`,
        toFilterGroup(filterControls, filterValues),
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

  const removeWidget = useMutation({
    mutationFn: (widgetId: string) => api.delete(`/dashboards/${id}/widgets/${widgetId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', id] })
    },
  })

  const allWidgets = dashboard.data?.widgets ?? []
  const pages = dashboard.data?.pages ?? []
  // A dashboard with no named pages is one unnamed page, which is what every
  // dashboard made before this feature is.
  const pageCount = Math.max(1, pages.length)
  const page = Math.min(activePage, pageCount - 1)
  const widgets = useMemo(
    () => allWidgets.filter((widget) => (widget.page ?? 0) === page),
    [allWidgets, page],
  )

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
    <div ref={(node) => node && setWidth(node.clientWidth)}>
      <PageHeader
        title={dashboard.data!.name}
        description={dashboard.data!.description}
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
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-brand-200 bg-brand-50 px-4 py-2.5 text-sm text-brand-800">
          <Badge tone="info" icon="⇗">
            Public
          </Badge>
          <span>Anyone with this link can view the dashboard:</span>
          <code className="rounded bg-white px-2 py-0.5 text-xs">
            {location.origin}/shared/{dashboard.data!.public_token}
          </code>
        </div>
      )}

      <DashboardFilters
        controls={filterControls}
        value={filterValues}
        onChange={setFilterValues}
      />

      <PageTabs
        pages={pages}
        active={page}
        count={pageCount}
        canEdit={!isPublic && can('analyst')}
        widgetsOnPage={widgets.length}
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
        <GridLayout
          className="layout"
          layout={layout}
          cols={COLUMNS}
          rowHeight={ROW_HEIGHT}
          width={width}
          margin={[16, 16]}
          isDraggable={editing && !isPublic}
          isResizable={editing && !isPublic}
          onDragStop={onLayoutChange}
          onResizeStop={onLayoutChange}
          draggableHandle=".widget-handle"
        >
          {widgets.map((widget) => (
            <div key={widget.id} className="card overflow-hidden">
              <WidgetFrame
                widget={widget}
                payload={rendered.data?.widgets[widget.id]}
                loading={rendered.isLoading}
                editing={editing && !isPublic}
                canEdit={!isPublic && can('analyst')}
                theme={dashboard.data!.theme ?? 'default'}
                onRemove={() => {
                  if (confirm(`Remove "${widget.title || 'this widget'}" from the dashboard?`))
                    removeWidget.mutate(widget.id)
                }}
              />
            </div>
          ))}
        </GridLayout>
      )}

      {adding && (
        <AddWidgetModal dashboardId={id} page={page} onClose={() => setAdding(false)} />
      )}
      {editingFilters && (
        <FilterControlsModal
          dashboardId={id}
          widgets={allWidgets}
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
  onRemove,
}: {
  widget: Widget
  payload: any
  loading: boolean
  editing: boolean
  canEdit: boolean
  /** The dashboard's categorical ordering, applied to every chart on it. */
  theme: string
  onRemove: () => void
}) {
  return (
    <div className="flex h-full flex-col">
      <header className="widget-handle group flex shrink-0 items-center justify-between gap-2 border-b border-ink-200 px-4 py-2.5">
        <h3 className={`truncate text-sm font-semibold text-ink-800 ${editing ? 'cursor-move' : ''}`}>
          {widget.title || payload?.name || 'Widget'}
        </h3>
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
      </header>
      <div className="flex min-h-0 flex-1 flex-col overflow-auto p-4">
        {loading ? (
          <Loading />
        ) : !payload ? (
          <p className="py-6 text-center text-sm text-ink-400">No data</p>
        ) : payload.error ? (
          <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {payload.error}
          </p>
        ) : payload.type === 'indicator' ? (
          <IndicatorWidget payload={payload} />
        ) : payload.type === 'quality' ? (
          <QualityWidget payload={payload} />
        ) : payload.type === 'crosstab' ? (
          <CrosstabTable result={payload.result} compact fill />
        ) : payload.type === 'text' ? (
          <p className="whitespace-pre-wrap text-sm text-ink-700">{payload.content}</p>
        ) : payload.result ? (
          <ChartCard
            result={payload.result}
            chartType={payload.chart_type ?? 'bar'}
            fill
            showToggle={false}
            theme={theme}
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
  onSelect,
  onChange,
}: {
  pages: { name?: string }[]
  active: number
  count: number
  canEdit: boolean
  widgetsOnPage: number
  onSelect: (index: number) => void
  onChange: (pages: { name: string }[]) => void
}) {
  const named = Array.from({ length: count }, (_, index) => ({
    name: pages[index]?.name || `Page ${index + 1}`,
  }))

  const addPage = () => {
    const name = prompt('Name for the new page')?.trim()
    if (!name) return
    onChange([...named, { name }])
    onSelect(count)
  }

  const renamePage = (index: number) => {
    const name = prompt('Rename this page', named[index].name)?.trim()
    if (!name) return
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
    <div className="mb-4 flex flex-wrap items-center gap-1 border-b border-ink-200">
      {count > 1 &&
        named.map((page, index) => (
          <button
            key={index}
            onClick={() => onSelect(index)}
            onDoubleClick={() => canEdit && renamePage(index)}
            title={canEdit ? 'Double-click to rename' : undefined}
            className={`whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors ${
              active === index
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-ink-500 hover:text-ink-800'
            }`}
          >
            {page.name}
          </button>
        ))}
      {canEdit && (
        <>
          <button className="btn-ghost btn-sm text-ink-500" onClick={addPage}>
            + Page
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
              className="rounded-lg border border-red-200 bg-red-50 px-3 py-2"
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

function IndicatorWidget({ payload }: { payload: any }) {
  const color = STATUS_COLORS[payload.status as keyof typeof STATUS_COLORS] ?? STATUS_COLORS.unknown
  return (
    <div className="flex h-full flex-col justify-center">
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
  const [kind, setKind] = useState<'chart' | 'indicator' | 'quality' | 'text'>('chart')
  const [datasetId, setDatasetId] = useState('')
  const [chartId, setChartId] = useState('')
  const [indicatorId, setIndicatorId] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')

  const charts = useQuery({ queryKey: ['charts'], queryFn: () => api.get<Chart[]>('/dashboards/charts') })
  const indicators = useQuery({
    queryKey: ['indicators'],
    queryFn: () => api.get<Indicator[]>('/monitoring/indicators'),
  })
  const datasets = useQuery({
    queryKey: ['datasets'],
    queryFn: () => api.get<Page<Dataset>>('/datasets?limit=200'),
    enabled: kind === 'quality',
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
              : indicators.data?.find((i) => i.id === indicatorId)?.name) ||
          'Widget',
        widget_type: kind,
        chart_id: kind === 'chart' ? chartId : null,
        indicator_id: kind === 'indicator' ? indicatorId : null,
        dataset_id: kind === 'quality' ? datasetId : null,
        page,
        config: kind === 'text' ? { content } : {},
        layout: kind === 'indicator' ? { w: 3, h: 3 } : { w: 6, h: 4 },
      }),
    onSuccess: () => {
      toast.push('Widget added', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', dashboardId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', dashboardId] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const canAdd =
    (kind === 'chart' && chartId) ||
    (kind === 'indicator' && indicatorId) ||
    (kind === 'quality' && datasetId) ||
    (kind === 'text' && content)

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
  widgets,
  controls,
  onClose,
}: {
  dashboardId: string
  widgets: Widget[]
  controls: FilterControl[]
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [chosen, setChosen] = useState<FilterControl[]>(controls)

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
    mutationFn: () => api.patch(`/dashboards/${dashboardId}`, { filters: chosen }),
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
      title="Dashboard filters"
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
        A filter narrows every widget whose dataset carries that variable, and
        leaves the others as they are — so it is still useful when only part of
        the page has it.
      </p>

      {details.isLoading || datasets.isLoading ? (
        <Loading />
      ) : !details.data?.length ? (
        <p className="text-sm text-ink-500">
          Add a widget first; the filters come from the datasets it uses.
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
