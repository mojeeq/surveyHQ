import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import { api } from '@/lib/api'
import { buildSparkline, STATUS_COLORS } from '@/lib/charts'
import { formatNumber, formatValue, relativeTime } from '@/lib/format'
import type { Alert, Dataset, IndicatorValue, MonitoringSummary, Page } from '@/lib/types'
import ProjectFilter, { projectParam } from '@/components/ProjectFilter'
import { Badge, Card, EmptyState, ErrorNote, Loading, PageHeader, Stat } from '@/components/ui'

const STATE_TONE = {
  ok: { tone: 'success', icon: '✓', label: 'On track' },
  warning: { tone: 'warning', icon: '▲', label: 'Watch' },
  critical: { tone: 'danger', icon: '■', label: 'Critical' },
  unknown: { tone: 'neutral', icon: '–', label: 'No data' },
} as const

export default function Overview() {
  // Null is every project at once, which is what the page has always shown.
  const [project, setProject] = useState<string | null>(null)
  const scope = projectParam(project)

  const summary = useQuery({
    queryKey: ['monitoring-summary', project],
    queryFn: () =>
      api.get<MonitoringSummary>(`/monitoring/summary?${scope.slice(1)}`),
    refetchInterval: 60_000,
  })
  const indicators = useQuery({
    queryKey: ['indicator-values', project],
    queryFn: () =>
      api.get<IndicatorValue[]>(`/monitoring/indicators/values?trend_points=30${scope}`),
  })
  const datasets = useQuery({
    queryKey: ['datasets', 'recent', project],
    queryFn: () => api.get<Page<Dataset>>(`/datasets?limit=6${scope}`),
  })
  const alerts = useQuery({
    queryKey: ['alerts', 'open', project],
    queryFn: () =>
      api.get<Alert[]>(`/monitoring/alerts?status=open&limit=5${scope}`),
  })

  if (summary.isLoading) return <Loading label="Loading your overview" />
  if (summary.error) return <ErrorNote error={summary.error} retry={summary.refetch} />

  const stats = summary.data!

  return (
    <>
      <PageHeader
        title="Overview"
        description="Field progress, indicator health and anything that needs attention."
        actions={<ProjectFilter value={project} onChange={setProject} />}
      />

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
              <Link to="/monitoring" className="btn-secondary btn-sm">
                Manage
              </Link>
            }
          >
            {indicators.isLoading ? (
              <Loading />
            ) : !indicators.data?.length ? (
              <EmptyState
                icon="◎"
                title="No indicators yet"
                description="Create indicators to track completion, response rates or any measure you monitor."
                action={
                  <Link to="/monitoring" className="btn-primary btn-sm">
                    Create an indicator
                  </Link>
                }
              />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {indicators.data.map((indicator) => (
                  <IndicatorTile key={indicator.indicator_id} indicator={indicator} />
                ))}
              </div>
            )}
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
            {!alerts.data?.length ? (
              <p className="py-6 text-center text-sm text-ink-500">
                Nothing is flagged right now.
              </p>
            ) : (
              <ul className="space-y-3">
                {alerts.data.map((alert) => (
                  <li key={alert.id} className="border-l-2 border-red-400 pl-3">
                    <div className="flex items-center gap-2">
                      <Badge
                        tone={alert.severity === 'critical' ? 'danger' : 'warning'}
                        icon={alert.severity === 'critical' ? '■' : '▲'}
                      >
                        {alert.severity}
                      </Badge>
                      <span className="text-xs text-ink-400">
                        {relativeTime(alert.created_at)}
                      </span>
                    </div>
                    <p className="mt-1 text-sm font-medium text-ink-800">{alert.title}</p>
                    <p className="text-xs text-ink-500">{alert.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card
            title="Recent datasets"
            actions={
              <Link to="/datasets" className="btn-secondary btn-sm">
                All datasets
              </Link>
            }
          >
            {!datasets.data?.items.length ? (
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
            ) : (
              <ul className="divide-y divide-ink-100">
                {datasets.data.items.map((dataset) => (
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
          </Card>
        </div>
      </div>
    </>
  )
}

function IndicatorTile({ indicator }: { indicator: IndicatorValue }) {
  const state = STATE_TONE[indicator.status] ?? STATE_TONE.unknown
  const progress = indicator.progress_percent
  return (
    <div className="rounded-card border border-ink-200 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-ink-700">{indicator.name}</p>
        <Badge tone={state.tone} icon={state.icon}>
          {state.label}
        </Badge>
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-ink-900">
        {formatValue(indicator.value, indicator.value_format, indicator.unit)}
      </p>
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
            {progress?.toFixed(0) ?? '–'}% of target {formatNumber(indicator.target_value)}
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
