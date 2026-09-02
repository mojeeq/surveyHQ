import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import GridLayout, { type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { STATUS_COLORS } from '@/lib/charts'
import { formatNumber, formatValue, relativeTime } from '@/lib/format'
import type { Chart, Dashboard, Indicator, Widget } from '@/lib/types'
import AssignProject from '@/components/AssignProject'
import ChartCard from '@/components/ChartCard'
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
  const [width, setWidth] = useState(1200)

  const isPublic = Boolean(publicToken)
  const basePath = isPublic ? `/public/dashboards/${publicToken}` : `/dashboards/${id}`

  const dashboard = useQuery({
    queryKey: ['dashboard', id, publicToken],
    queryFn: () => api.get<Dashboard>(basePath),
  })

  const rendered = useQuery({
    queryKey: ['dashboard-data', id, publicToken],
    queryFn: () =>
      api.post<{ widgets: Record<string, any> }>(`${basePath}/data`, {
        op: 'and',
        conditions: [],
        groups: [],
      }),
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

  const removeWidget = useMutation({
    mutationFn: (widgetId: string) => api.delete(`/dashboards/${id}/widgets/${widgetId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', id] })
    },
  })

  const widgets = dashboard.data?.widgets ?? []

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
    const updated = widgets.map((widget) => {
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
                onRemove={() => {
                  if (confirm(`Remove "${widget.title || 'this widget'}" from the dashboard?`))
                    removeWidget.mutate(widget.id)
                }}
              />
            </div>
          ))}
        </GridLayout>
      )}

      {adding && <AddWidgetModal dashboardId={id} onClose={() => setAdding(false)} />}
    </div>
  )
}

function WidgetFrame({
  widget,
  payload,
  loading,
  editing,
  canEdit,
  onRemove,
}: {
  widget: Widget
  payload: any
  loading: boolean
  editing: boolean
  canEdit: boolean
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
        ) : payload.type === 'crosstab' ? (
          <CrosstabTable result={payload.result} compact maxHeight={260} />
        ) : payload.type === 'text' ? (
          <p className="whitespace-pre-wrap text-sm text-ink-700">{payload.content}</p>
        ) : payload.result ? (
          <ChartCard
            result={payload.result}
            chartType={payload.chart_type ?? 'bar'}
            fill
            showToggle={false}
          />
        ) : null}
      </div>
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

function AddWidgetModal({ dashboardId, onClose }: { dashboardId: string; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<'chart' | 'indicator' | 'text'>('chart')
  const [chartId, setChartId] = useState('')
  const [indicatorId, setIndicatorId] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')

  const charts = useQuery({ queryKey: ['charts'], queryFn: () => api.get<Chart[]>('/dashboards/charts') })
  const indicators = useQuery({
    queryKey: ['indicators'],
    queryFn: () => api.get<Indicator[]>('/monitoring/indicators'),
  })

  const add = useMutation({
    mutationFn: () =>
      api.post(`/dashboards/${dashboardId}/widgets`, {
        title:
          title ||
          (kind === 'chart'
            ? charts.data?.find((c) => c.id === chartId)?.name
            : indicators.data?.find((i) => i.id === indicatorId)?.name) ||
          'Widget',
        widget_type: kind,
        chart_id: kind === 'chart' ? chartId : null,
        indicator_id: kind === 'indicator' ? indicatorId : null,
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
    (kind === 'chart' && chartId) || (kind === 'indicator' && indicatorId) || (kind === 'text' && content)

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
