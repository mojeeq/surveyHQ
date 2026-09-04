import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { relativeTime } from '@/lib/format'
import type { Chart, Dashboard } from '@/lib/types'
import ChartCard from '@/components/ChartCard'
import CrosstabTable from '@/components/CrosstabTable'
import ErrorBoundary from '@/components/ErrorBoundary'
import ProjectPicker from '@/components/ProjectPicker'
import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Tabs,
} from '@/components/ui'

export default function Dashboards() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'dashboards' | 'charts'>('dashboards')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [projectId, setProjectId] = useState('')

  const dashboards = useQuery({
    queryKey: ['dashboards'],
    queryFn: () => api.get<Dashboard[]>('/dashboards'),
  })
  const charts = useQuery({
    queryKey: ['charts'],
    queryFn: () => api.get<Chart[]>('/dashboards/charts'),
  })

  const create = useMutation({
    mutationFn: () =>
      api.post<Dashboard>('/dashboards', { name, project_id: projectId || null }),
    onSuccess: () => {
      toast.push('Dashboard created', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setCreating(false)
      setName('')
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const removeDashboard = useMutation({
    mutationFn: (id: string) => api.delete(`/dashboards/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboards'] }),
  })
  const removeChart = useMutation({
    mutationFn: (id: string) => api.delete(`/dashboards/charts/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['charts'] }),
  })

  return (
    <>
      <PageHeader
        title="Dashboards"
        description="Assemble saved charts and indicators into a monitoring view."
        actions={
          can('analyst') && (
            <button className="btn-primary" onClick={() => setCreating(true)}>
              New dashboard
            </button>
          )
        }
      />

      <Tabs
        tabs={[
          { id: 'dashboards', label: 'Dashboards', count: dashboards.data?.length },
          { id: 'charts', label: 'Saved charts', count: charts.data?.length },
        ]}
        active={tab}
        onChange={(id) => setTab(id as 'dashboards' | 'charts')}
      />

      <div className="mt-4">
        {tab === 'dashboards' &&
          (dashboards.isLoading ? (
            <Loading />
          ) : dashboards.error ? (
            <ErrorNote error={dashboards.error} />
          ) : !dashboards.data?.length ? (
            <Card>
              <EmptyState
                icon="▦"
                title="No dashboards yet"
                description="Create a dashboard, then add charts you saved from Explore or indicators from Monitoring."
                action={
                  can('analyst') && (
                    <button className="btn-primary btn-sm" onClick={() => setCreating(true)}>
                      Create a dashboard
                    </button>
                  )
                }
              />
            </Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {dashboards.data.map((dashboard) => (
                <article key={dashboard.id} className="card flex flex-col p-5">
                  <div className="flex items-start justify-between gap-2">
                    <Link
                      to={`/dashboards/${dashboard.id}`}
                      className="text-base font-semibold text-ink-900 hover:text-brand-700"
                    >
                      {dashboard.name}
                    </Link>
                    {dashboard.is_public && (
                      <Badge tone="info" icon="⇗">
                        Shared
                      </Badge>
                    )}
                  </div>
                  {dashboard.description && (
                    <p className="mt-1 line-clamp-2 text-sm text-ink-500">
                      {dashboard.description}
                    </p>
                  )}
                  <div className="mt-4 flex items-center justify-between border-t border-ink-100 pt-3">
                    <span className="text-xs text-ink-400">
                      Updated {relativeTime(dashboard.updated_at)}
                    </span>
                    <div className="flex gap-1">
                      <Link to={`/dashboards/${dashboard.id}`} className="btn-ghost btn-sm">
                        Open
                      </Link>
                      {can('analyst') && (
                        <button
                          className="btn-ghost btn-sm text-red-600"
                          onClick={() => {
                            if (confirm(`Delete the dashboard "${dashboard.name}"?`))
                              removeDashboard.mutate(dashboard.id)
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ))}

        {tab === 'charts' &&
          (charts.isLoading ? (
            <Loading />
          ) : !charts.data?.length ? (
            <Card>
              <EmptyState
                icon="◱"
                title="No saved charts"
                description="Build a query in Explore and use 'Save as chart' to reuse it on dashboards."
                action={
                  <Link to="/explore" className="btn-primary btn-sm">
                    Go to Explore
                  </Link>
                }
              />
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {charts.data.map((chart) => (
                <ErrorBoundary key={chart.id} what={`"${chart.name}"`}>
                  <ChartPreview
                    chart={chart}
                    canDelete={can('analyst')}
                    onDelete={() => {
                      if (confirm(`Delete the chart "${chart.name}"?`)) removeChart.mutate(chart.id)
                    }}
                  />
                </ErrorBoundary>
              ))}
            </div>
          ))}
      </div>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="New dashboard"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setCreating(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={() => create.mutate()} disabled={!name}>
              Create
            </button>
          </>
        }
      >
        <Field label="Dashboard name">
          <input
            className="input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Daily field monitoring"
            autoFocus
          />
        </Field>
        <ProjectPicker value={projectId} onChange={setProjectId} />
      </Modal>
    </>
  )
}

function ChartPreview({
  chart,
  canDelete,
  onDelete,
}: {
  chart: Chart
  canDelete: boolean
  onDelete: () => void
}) {
  const data = useQuery({
    queryKey: ['chart-data', chart.id],
    queryFn: () =>
      api.post<any>(`/dashboards/charts/${chart.id}/data`, {
        op: 'and',
        conditions: [],
        groups: [],
      }),
  })

  return (
    <Card
      title={chart.name}
      subtitle={chart.description || chart.chart_type.replace('_', ' ')}
      actions={
        canDelete && (
          <>
            {/* Editing a chart is changing the query it was built from, and
                Explore is where that was done in the first place. */}
            <Link className="btn-ghost btn-sm" to={`/explore?chart=${chart.id}`}>
              Edit
            </Link>
            <button className="btn-ghost btn-sm text-red-600" onClick={onDelete}>
              Delete
            </button>
          </>
        )
      }
    >
      {data.isLoading ? (
        <Loading />
      ) : data.error ? (
        <ErrorNote error={data.error} />
      ) : chart.chart_type === 'crosstab' ? (
        // A saved cross-tab answers with a table, not a series: it has row and
        // column labels and a grid, where a chart expects columns and rows.
        // Handing one to the chart renderer is what used to blank this page.
        <CrosstabTable result={data.data} compact maxHeight={260} />
      ) : (
        <ChartCard
          result={data.data}
          chartType={chart.chart_type}
          height={260}
          display={(chart.spec as any)?.options}
        />
      )}
    </Card>
  )
}
