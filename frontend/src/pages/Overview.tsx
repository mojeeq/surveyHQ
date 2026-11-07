import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactECharts from '@/components/ReactECharts'
import { api } from '@/lib/api'
import { buildSparkline, STATUS_COLORS } from '@/lib/charts'
import { formatNumber, formatValue, relativeTime } from '@/lib/format'
import type { Alert, Dataset, IndicatorValue, MonitoringSummary, Page } from '@/lib/types'
import ProjectFilter, { projectParam } from '@/components/ProjectFilter'
import IndicatorMovement from '@/components/monitoring/IndicatorMovement'
import GettingStarted from '@/components/GettingStarted'
import {
  type AttentionItem,
  NeedsAttentionBody,
  PanelBody,
  StaleNote,
} from '@/components/overview/OverviewPanels'
import { indicatorBadge } from '@/lib/indicator-status'
import { attentionPanel, panelState } from '@/lib/panel-state'
import { Badge, Card, EmptyState, ErrorNote, Loading, PageHeader, Stat } from '@/components/ui'

/** How often every panel on the page is refreshed together. */
const REFRESH_MS = 60_000

export default function Overview() {
  // Null is every project at once, which is what the page has always shown.
  const [project, setProject] = useState<string | null>(null)
  const scope = projectParam(project)

  // The totals and the panels under them are refreshed together, on one
  // timer and when the tab is returned to, so they can't disagree with each
  // other for a minute at a time.
  const live = { refetchOnWindowFocus: true } as const
  const summary = useQuery({
    queryKey: ['monitoring-summary', project],
    queryFn: () =>
      api.get<MonitoringSummary>(`/monitoring/summary?${scope.slice(1)}`),
    ...live,
  })
  const indicators = useQuery({
    queryKey: ['indicator-values', project],
    queryFn: () =>
      api.get<IndicatorValue[]>(`/monitoring/indicators/values?trend_points=30${scope}`),
    ...live,
  })
  const datasets = useQuery({
    queryKey: ['datasets', 'recent', project],
    queryFn: () => api.get<Page<Dataset>>(`/datasets?limit=6${scope}`),
    ...live,
  })
  const attention = useQuery({
    queryKey: ['attention', project],
    queryFn: () => api.get<AttentionItem[]>(`/monitoring/attention?limit=8${scope}`),
    ...live,
  })
  const alerts = useQuery({
    queryKey: ['alerts', 'open', project],
    queryFn: () =>
      api.get<Alert[]>(`/monitoring/alerts?status=open&limit=5${scope}`),
    ...live,
  })

  const { refetch: refetchSummary } = summary
  const { refetch: refetchIndicators } = indicators
  const { refetch: refetchDatasets } = datasets
  const { refetch: refetchAttention } = attention
  const { refetch: refetchAlerts } = alerts
  const refreshAll = useCallback(
    () =>
      Promise.all([
        refetchSummary(),
        refetchIndicators(),
        refetchDatasets(),
        refetchAttention(),
        refetchAlerts(),
      ]),
    [refetchSummary, refetchIndicators, refetchDatasets, refetchAttention, refetchAlerts],
  )
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refreshAll()
    }, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [refreshAll])

  const refreshing = [summary, indicators, datasets, attention, alerts].some((q) => q.isFetching)

  if (summary.data === undefined) {
    if (summary.error) return <ErrorNote error={summary.error} retry={summary.refetch} />
    return <Loading label="Loading your overview" />
  }
  const stats = summary.data

  const indicatorPanel = panelState(indicators, (rows) => rows.length === 0)
  const datasetPanel = panelState(datasets, (page) => page.items.length === 0)
  const needsAttention = attentionPanel(
    { label: 'problems', query: attention },
    { label: 'open alerts', query: alerts },
  )

  return (
    <>
      <PageHeader
        title="Overview"
        description="Field progress, indicator health and anything that needs attention."
        actions={
          <div className="flex items-center gap-2">
            <span className="hidden text-xs text-ink-500 sm:inline" title="Refreshes every minute">
              Updated {relativeTime(new Date(summary.dataUpdatedAt).toISOString())}
            </span>
            <button
              type="button"
              className="btn-secondary btn-sm"
              onClick={() => void refreshAll()}
              disabled={refreshing}
            >
              {refreshing ? 'Refreshing…' : 'Refresh'}
            </button>
            <ProjectFilter value={project} onChange={setProject} />
          </div>
        }
      />

      <GettingStarted />

      {summary.error ? (
        <StaleNote what="the totals" updatedAt={summary.dataUpdatedAt} retry={() => void refreshAll()} />
      ) : null}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="Records collected"
          value={formatNumber(stats.total_records)}
          hint={`across ${stats.datasets} dataset${stats.datasets === 1 ? '' : 's'}`}
        />
        <Stat
          label="Indicators tracked"
          value={stats.indicators}
          hint={`${stats.indicators_ok} on track, ${stats.indicators_warning} watch`}
          tone={stats.indicators_critical > 0 ? 'danger' : 'neutral'}
        />
        <Stat
          label="Open alerts"
          value={stats.open_alerts}
          hint={stats.critical_alerts > 0 ? `${stats.critical_alerts} critical` : 'nothing critical'}
          tone={stats.open_alerts > 0 ? 'warning' : 'success'}
        />
        <Stat
          label="Failing checks"
          value={stats.failing_quality_checks}
          hint="data quality rules"
          tone={stats.failing_quality_checks > 0 ? 'danger' : 'success'}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card
            title="Indicators"
            subtitle="Live values against their targets"
            actions={
              <Link to="/indicators" className="btn-secondary btn-sm">
                Manage
              </Link>
            }
          >
            <PanelBody
              panel={indicatorPanel}
              what="indicators"
              retry={() => void indicators.refetch()}
              empty={
                <EmptyState
                  icon="◎"
                  title="No indicators yet"
                  description="Create indicators to track completion, response rates or any measure you monitor."
                  action={
                    <Link to="/indicators" className="btn-primary btn-sm">
                      Create an indicator
                    </Link>
                  }
                />
              }
            >
              {(rows) => (
                <div className="grid gap-3 sm:grid-cols-2">
                  {rows.map((indicator) => (
                    <IndicatorTile key={indicator.indicator_id} indicator={indicator} />
                  ))}
                </div>
              )}
            </PanelBody>
          </Card>
        </div>

        <div className="space-y-6">
          <Card
            title="Needs attention"
            actions={
              <Link to="/alerts" className="btn-secondary btn-sm">
                All alerts
              </Link>
            }
          >
            <NeedsAttentionBody
              panel={needsAttention}
              retry={() => void Promise.all([attention.refetch(), alerts.refetch()])}
            />
          </Card>

          <Card
            title="Recent datasets"
            actions={
              <Link to="/datasets" className="btn-secondary btn-sm">
                All datasets
              </Link>
            }
          >
            <PanelBody
              panel={datasetPanel}
              what="datasets"
              retry={() => void datasets.refetch()}
              empty={
                <EmptyState
                  icon="▤"
                  title="No data yet"
                  description="Upload a Stata file or connect a Survey Solutions server."
                  action={
                    <Link to="/datasets" className="btn-primary btn-sm">
                      Add data
                    </Link>
                  }
                />
              }
            >
              {(page) => (
                <ul className="divide-y divide-ink-100">
                  {page.items.map((dataset) => (
                    <li key={dataset.id}>
                      <Link
                        to={`/datasets/${dataset.id}`}
                        className="-mx-2 flex items-center justify-between rounded px-2 py-2.5 hover:bg-ink-50"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-ink-800">
                            {dataset.name}
                          </p>
                          <p className="text-xs text-ink-500">
                            {formatNumber(dataset.row_count)} rows · {dataset.column_count} columns
                          </p>
                        </div>
                        {dataset.status !== 'ready' && (
                          <Badge tone={dataset.status === 'failed' ? 'danger' : 'warning'}>
                            {dataset.status}
                          </Badge>
                        )}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </PanelBody>
          </Card>
        </div>
      </div>
    </>
  )
}

function IndicatorTile({ indicator }: { indicator: IndicatorValue }) {
  const state = indicatorBadge(indicator)
  const progress = indicator.progress_percent
  return (
    <div className="rounded-card border border-ink-200 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-ink-700">{indicator.name}</p>
        <Badge tone={state.tone} icon={state.icon} title={state.title}>
          {state.label}
        </Badge>
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-ink-900">
        {formatValue(indicator.value, indicator.value_format, indicator.unit)}
      </p>
      <IndicatorMovement
        movement={indicator.movement}
        format={indicator.value_format}
        unit={indicator.unit}
        direction={indicator.direction}
        target={indicator.target_value}
      />
      {indicator.target_value !== null && (
        <>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-100">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(progress ?? 0, 100)}%`,
                backgroundColor: STATUS_COLORS[indicator.status] ?? STATUS_COLORS.unknown,
              }}
            />
          </div>
          <p className="mt-1 text-xs text-ink-500">
            {progress?.toFixed(0) ?? '-'}% of target {formatNumber(indicator.target_value)}
          </p>
        </>
      )}
      {indicator.trend.length > 2 && (
        <div className="mt-2 -mb-1">
          <ReactECharts option={buildSparkline(indicator.trend)} style={{ height: 40 }} notMerge />
        </div>
      )}
    </div>
  )
}
