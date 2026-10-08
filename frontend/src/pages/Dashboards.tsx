import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { relativeTime } from '@/lib/format'
import type { Chart, Dashboard } from '@/lib/types'
import type { Direction, Sortable } from '@/lib/collections'
import { arrange } from '@/lib/collections'
import { useRemembered } from '@/hooks/useRemembered'
import CollectionBar, {
  SortHeader,
  VIEW_MODES,
  type SortOption,
  type ViewMode,
} from '@/components/CollectionBar'
import ChartCard from '@/components/ChartCard'
import DashboardSketch from '@/components/DashboardSketch'
import CrosstabTable from '@/components/CrosstabTable'
import ErrorBoundary from '@/components/ErrorBoundary'
import ProjectPicker from '@/components/ProjectPicker'
import ProjectFilter from '@/components/ProjectFilter'
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

/** What the dashboard list can be ordered by. */
const ORDERS: Record<string, (dashboard: Dashboard) => Sortable> = {
  updated: (dashboard) => dashboard.updated_at,
  name: (dashboard) => dashboard.name,
  widgets: (dashboard) => dashboard.widget_count ?? 0,
  pages: (dashboard) => dashboard.page_count ?? 1,
  created: (dashboard) => dashboard.created_at,
}

const SORTS: SortOption[] = [
  { key: 'updated', label: 'Last updated' },
  { key: 'name', label: 'Name' },
  { key: 'widgets', label: 'Widgets' },
  { key: 'pages', label: 'Pages' },
  { key: 'created', label: 'Created' },
]

const SORT_KEYS = Object.keys(ORDERS)
const DIRECTIONS: readonly Direction[] = ['asc', 'desc']

type LibraryChart = Chart & {
  dataset_name: string
  project_id: string | null
  project_name: string | null
}

export default function Dashboards() {
  const { can } = useAuth()
  const toast = useToast()
  const ask = useDialog()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'dashboards' | 'charts'>('dashboards')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [projectId, setProjectId] = useState('')
  /** Which project this page is narrowed to. Null is all of them. */
  const [project, setProject] = useState<string | null>(null)
  const [datasetId, setDatasetId] = useState('')

  // Both lists take the same project filter. A dashboard carries a project of
  // its own; a chart takes one from its dataset. The chart-library endpoint also
  // returns the resolved dataset name so the UI can filter and identify charts
  // without reconstructing ownership from a separately paginated dataset list.
  const scope = new URLSearchParams(project === null ? {} : { project_id: project || 'none' })
  const query = scope.toString() ? `?${scope}` : ''

  const dashboards = useQuery({
    queryKey: ['dashboards', project],
    queryFn: () => api.get<Dashboard[]>(`/dashboards${query}`),
  })
  const charts = useQuery({
    queryKey: ['charts', 'library', project],
    queryFn: () => api.get<LibraryChart[]>(`/dashboards/chart-library${query}`),
  })

  const chartDatasets = Array.from(
    new Map(
      (charts.data ?? []).map((chart) => [
        chart.dataset_id,
        { id: chart.dataset_id, name: chart.dataset_name },
      ]),
    ).values(),
  ).sort((a, b) => a.name.localeCompare(b.name))

  const visibleCharts = datasetId
    ? (charts.data ?? []).filter((chart) => chart.dataset_id === datasetId)
    : (charts.data ?? [])

  const [search, setSearch] = useState('')
  // The endpoint already sends these most-recently-updated first, so that is
  // the default and the page opens exactly as it did before.
  const [sort, setSort] = useRemembered('dashboards.sort', 'updated', SORT_KEYS)
  const [direction, setDirection] = useRemembered<Direction>(
    'dashboards.direction',
    'desc',
    DIRECTIONS,
  )
  const [view, setView] = useRemembered<ViewMode>('dashboards.view', 'cards', VIEW_MODES)

  const allBoards = dashboards.data ?? []
  const shownBoards = arrange(allBoards, {
    query: search,
    searchable: (dashboard) => [dashboard.name, dashboard.description],
    read: ORDERS[sort] ?? ORDERS.updated,
    direction,
  })

  const orderBy = (column: string, next: Direction) => {
    setSort(column)
    setDirection(next)
  }

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

  /** The same question in the table and in the cards, asked once. */
  const confirmDelete = (name: string) =>
    ask.confirm({
      title: `Delete \u201C${name}\u201D?`,
      message: 'Its pages, widgets and saved views go with it. Charts stay.',
      confirmLabel: 'Delete dashboard',
      tone: 'danger',
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
          <div className="flex flex-wrap items-center gap-2">
            <ProjectFilter
              value={project}
              onChange={(next) => {
                setProject(next)
                setDatasetId('')
              }}
            />
            {can('analyst') && (
              <button className="btn-primary" onClick={() => setCreating(true)}>
                New dashboard
              </button>
            )}
          </div>
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
        {tab === 'dashboards' && !dashboards.isLoading && !dashboards.error && allBoards.length > 0 && (
          <CollectionBar
            noun="dashboard"
            shown={shownBoards.length}
            total={allBoards.length}
            query={search}
            onQuery={setSearch}
            sort={sort}
            onSort={setSort}
            direction={direction}
            onDirection={setDirection}
            options={SORTS}
            view={view}
            onView={setView}
          />
        )}

        {tab === 'dashboards' &&
          (dashboards.isLoading ? (
            <Loading />
          ) : dashboards.error ? (
            <ErrorNote error={dashboards.error} />
          ) : allBoards.length && !shownBoards.length ? (
            <Card>
              <EmptyState
                icon="▦"
                title="No dashboards match your search"
                description="Try fewer words, or a different spelling."
                action={
                  <button className="btn-secondary btn-sm" onClick={() => setSearch('')}>
                    Clear the search
                  </button>
                }
              />
            </Card>
          ) : !dashboards.data?.length ? (
            <Card>
              <EmptyState
                icon="▦"
                title={project === null ? 'No dashboards yet' : 'No dashboards in this project'}
                description={
                  project === null
                    ? 'Create a dashboard, then add charts you saved from Explore or indicators from Monitoring.'
                    : 'Nothing here yet. Choose another project, or create one in this one.'
                }
                action={
                  can('analyst') && (
                    <button className="btn-primary btn-sm" onClick={() => setCreating(true)}>
                      Create a dashboard
                    </button>
                  )
                }
              />
            </Card>
          ) : view === 'list' ? (
            <DashboardRows
              dashboards={shownBoards}
              sort={sort}
              direction={direction}
              onSort={orderBy}
              canDelete={can('analyst')}
              onDelete={async (dashboard) => {
                if (await confirmDelete(dashboard.name)) removeDashboard.mutate(dashboard.id)
              }}
            />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {shownBoards.map((dashboard) => (
                <DashboardCard
                  key={dashboard.id}
                  dashboard={dashboard}
                  canDelete={can('analyst')}
                  onDelete={async () => {
                    if (await confirmDelete(dashboard.name)) removeDashboard.mutate(dashboard.id)
                  }}
                />
              ))}
            </div>
          ))}

        {tab === 'charts' && (
          <>
            {!charts.isLoading && !charts.error && charts.data?.length ? (
              <div className="mb-4 flex flex-wrap items-center gap-3 rounded-card border border-ink-200 bg-white px-4 py-3 dark:border-dark-200 dark:bg-dark-100">
                <label className="flex items-center gap-2 text-sm text-ink-600 dark:text-dark-600">
                  Dataset
                  <select
                    className="input w-64 py-1.5"
                    value={datasetId}
                    onChange={(event) => setDatasetId(event.target.value)}
                  >
                    <option value="">All datasets</option>
                    {chartDatasets.map((dataset) => (
                      <option key={dataset.id} value={dataset.id}>
                        {dataset.name}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="text-xs text-ink-500 dark:text-dark-500">
                  Showing {visibleCharts.length} of {charts.data.length} saved chart
                  {charts.data.length === 1 ? '' : 's'}
                </span>
                {datasetId && (
                  <button className="btn-ghost btn-sm" onClick={() => setDatasetId('')}>
                    Clear dataset filter
                  </button>
                )}
              </div>
            ) : null}

            {charts.isLoading ? (
              <Loading />
            ) : charts.error ? (
              <ErrorNote error={charts.error} />
            ) : !charts.data?.length ? (
              <Card>
                <EmptyState
                  icon="◱"
                  title={project === null ? 'No saved charts' : 'No saved charts in this project'}
                  description={
                    project === null
                      ? "Build a query in Explore and use 'Save as chart' to reuse it on dashboards."
                      : 'A chart belongs to the project its dataset is in. Choose another project, or save one from Explore.'
                  }
                  action={
                    <Link to="/explore" className="btn-primary btn-sm">
                      Go to Explore
                    </Link>
                  }
                />
              </Card>
            ) : !visibleCharts.length ? (
              <Card>
                <EmptyState
                  icon="◱"
                  title="No saved charts for this dataset"
                  description="Choose another dataset or clear the dataset filter."
                  action={
                    <button className="btn-secondary btn-sm" onClick={() => setDatasetId('')}>
                      Show all datasets
                    </button>
                  }
                />
              </Card>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                {visibleCharts.map((chart) => (
                  <ErrorBoundary key={chart.id} what={`"${chart.name}"`}>
                    <ChartPreview
                      chart={chart}
                      canDelete={can('analyst')}
                      onDelete={async () => {
                        const sure = await ask.confirm({
                          title: `Delete the chart \u201C${chart.name}\u201D?`,
                          message: 'Dashboards showing it will lose the panel.',
                          confirmLabel: 'Delete chart',
                          tone: 'danger',
                        })
                        if (sure) removeChart.mutate(chart.id)
                      }}
                    />
                  </ErrorBoundary>
                ))}
              </div>
            )}
          </>
        )}
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

/**
 * One dashboard in the list, with a picture of itself.
 *
 * The thumbnail is the card: a list of names and timestamps says nothing about
 * which board is the one with the map on it, and the shape of a board is what
 * people actually recognise it by. It is drawn from the layout the list
 * endpoint sends, so a card costs nothing to draw beyond the list it is
 * already on.
 */
/**
 * The same dashboards as rows, for comparing rather than recognising.
 *
 * The thumbnail is what makes a card worth having, and a row has no room for
 * one - so a row earns its place by showing what a card cannot: every board's
 * widget count and page count lined up in a column you can read down.
 */
function DashboardRows({
  dashboards,
  sort,
  direction,
  onSort,
  canDelete,
  onDelete,
}: {
  dashboards: Dashboard[]
  sort: string
  direction: Direction
  onSort: (column: string, direction: Direction) => void
  canDelete: boolean
  onDelete: (dashboard: Dashboard) => void
}) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-ink-200 text-xs uppercase tracking-wide text-ink-500 dark:border-dark-200 dark:text-dark-500">
          <tr>
            <SortHeader label="Dashboard" column="name" sort={sort} direction={direction} onSort={onSort} />
            <SortHeader label="Widgets" column="widgets" sort={sort} direction={direction} onSort={onSort} align="right" />
            <SortHeader label="Pages" column="pages" sort={sort} direction={direction} onSort={onSort} align="right" />
            <SortHeader label="Updated" column="updated" sort={sort} direction={direction} onSort={onSort} />
            <th className="px-3 py-2 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {dashboards.map((dashboard) => (
            <tr
              key={dashboard.id}
              className="border-b border-ink-100 last:border-0 hover:bg-ink-50 dark:border-dark-200 dark:hover:bg-dark-100"
            >
              <td className="px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <Link
                    to={`/dashboards/${dashboard.id}`}
                    className="font-medium text-ink-900 hover:text-brand-700 dark:text-dark-900 dark:hover:text-brand-400"
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
                  <p className="line-clamp-1 text-xs text-ink-500 dark:text-dark-500">
                    {dashboard.description}
                  </p>
                )}
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">{dashboard.widget_count ?? 0}</td>
              <td className="px-3 py-2.5 text-right tabular-nums">{dashboard.page_count ?? 1}</td>
              <td className="whitespace-nowrap px-3 py-2.5 text-ink-500 dark:text-dark-500">
                {relativeTime(dashboard.updated_at)}
              </td>
              <td className="whitespace-nowrap px-3 py-2.5 text-right">
                <Link to={`/dashboards/${dashboard.id}`} className="btn-ghost btn-sm">
                  Open
                </Link>
                {canDelete && (
                  <button
                    className="btn-ghost btn-sm text-red-600"
                    onClick={() => onDelete(dashboard)}
                  >
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DashboardCard({
  dashboard,
  canDelete,
  onDelete,
}: {
  dashboard: Dashboard
  canDelete: boolean
  onDelete: () => void
}) {
  const to = `/dashboards/${dashboard.id}`
  const widgets = dashboard.widget_count ?? 0
  const pages = dashboard.page_count ?? 1
  const hidden = widgets - (dashboard.sketch?.length ?? 0)

  // A board whose later pages or capped first page hold widgets the picture
  // does not would otherwise look emptier than it is.
  const made = [
    `${widgets} widget${widgets === 1 ? '' : 's'}`,
    pages > 1 ? `${pages} pages` : hidden > 0 ? `${hidden} not shown` : '',
    relativeTime(dashboard.updated_at),
  ].filter(Boolean)

  return (
    <article className="card group flex flex-col overflow-hidden">
      <div className="relative">
        <Link to={to} className="block" aria-label={`Open ${dashboard.name}`}>
          <DashboardSketch
            widgets={dashboard.sketch ?? []}
            appearance={dashboard.appearance}
            className="h-40 border-b border-ink-100 dark:border-dark-200"
          />
        </Link>
        {/* On the picture rather than beside the title: a badge in the title
            row wraps the name of any board called more than two words. */}
        {dashboard.is_public && (
          <span className="absolute right-2 top-2">
            <Badge tone="info" icon="⇗">
              Shared
            </Badge>
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col p-5">
        <Link
          to={to}
          className="text-base font-semibold text-ink-900 hover:text-brand-700 dark:text-dark-900 dark:hover:text-brand-400"
        >
          {dashboard.name}
        </Link>
        {dashboard.description && (
          <p className="mt-1 line-clamp-2 text-sm text-ink-500">{dashboard.description}</p>
        )}

        <div className="mt-auto flex items-center justify-between gap-2 border-t border-ink-100 pt-3 dark:border-dark-200">
          <span className="text-xs text-ink-400">{made.join(' \u00b7 ')}</span>
          <div className="flex shrink-0 gap-1">
            <Link to={to} className="btn-ghost btn-sm">
              Open
            </Link>
            {canDelete && (
              <button className="btn-ghost btn-sm text-red-600" onClick={onDelete}>
                Delete
              </button>
            )}
          </div>
        </div>
      </div>
    </article>
  )
}

function ChartPreview({
  chart,
  canDelete,
  onDelete,
}: {
  chart: LibraryChart
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
      <p className="mb-3 text-xs font-medium text-ink-500 dark:text-dark-500">
        {chart.dataset_name}
      </p>
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
