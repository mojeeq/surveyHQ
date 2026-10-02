import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime } from '@/lib/format'
import type { Project, ProjectStatus } from '@/lib/types'
import type { Direction, Sortable } from '@/lib/collections'
import { arrange } from '@/lib/collections'
import { useRemembered } from '@/hooks/useRemembered'
import CollectionBar, {
  SortHeader,
  VIEW_MODES,
  type SortOption,
  type ViewMode,
} from '@/components/CollectionBar'
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

/** What the list can be ordered by, and where each order reads its value. */
const ORDERS: Record<string, (project: Project) => Sortable> = {
  name: (project) => project.name,
  updated: (project) => project.updated_at,
  status: (project) => project.status,
  datasets: (project) => project.dataset_count,
  dashboards: (project) => project.dashboard_count,
  members: (project) => project.member_count,
}

const SORTS: SortOption[] = [
  { key: 'name', label: 'Name' },
  { key: 'updated', label: 'Last updated' },
  { key: 'status', label: 'Status' },
  { key: 'datasets', label: 'Datasets' },
  { key: 'dashboards', label: 'Dashboards' },
  { key: 'members', label: 'Members' },
]

const SORT_KEYS = Object.keys(ORDERS)
const DIRECTIONS: readonly Direction[] = ['asc', 'desc']

const STATUS_TONE: Record<ProjectStatus, 'success' | 'warning' | 'neutral'> = {
  active: 'success',
  paused: 'warning',
  closed: 'neutral',
  // Not a warning: archiving is a thing somebody chose to do, and the project
  // is intact apart from its data.
  archived: 'neutral',
}

export default function Projects() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)

  const [query, setQuery] = useState('')
  // The server already sends these ordered by name, so that is the default:
  // the page looks the same on opening as it always has.
  const [sort, setSort] = useRemembered('projects.sort', 'name', SORT_KEYS)
  const [direction, setDirection] = useRemembered<Direction>(
    'projects.direction',
    'asc',
    DIRECTIONS,
  )
  const [view, setView] = useRemembered<ViewMode>('projects.view', 'cards', VIEW_MODES)

  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<Project[]>('/projects'),
  })

  const all = projects.data ?? []
  const shown = arrange(all, {
    query,
    searchable: (project) => [project.name, project.description, project.status],
    read: ORDERS[sort] ?? ORDERS.name,
    direction,
  })

  const orderBy = (column: string, next: Direction) => {
    setSort(column)
    setDirection(next)
  }

  return (
    <>
      <PageHeader
        title="Projects"
        description="Group datasets and dashboards, and decide who can reach them."
        actions={
          can('manager') && (
            <button className="btn-primary" onClick={() => setCreating(true)}>
              New project
            </button>
          )
        }
      />

      {!projects.isLoading && !projects.error && all.length > 0 && (
        <CollectionBar
          noun="project"
          shown={shown.length}
          total={all.length}
          query={query}
          onQuery={setQuery}
          sort={sort}
          onSort={setSort}
          direction={direction}
          onDirection={setDirection}
          options={SORTS}
          view={view}
          onView={setView}
        />
      )}

      {projects.isLoading ? (
        <Loading />
      ) : projects.error ? (
        <ErrorNote error={projects.error} retry={() => projects.refetch()} />
      ) : all.length && !shown.length ? (
        <Card>
          <EmptyState
            icon="◫"
            title="No projects match your search"
            description="Try fewer words, or a different spelling."
            action={
              <button className="btn-secondary btn-sm" onClick={() => setQuery('')}>
                Clear the search
              </button>
            }
          />
        </Card>
      ) : !projects.data?.length ? (
        <Card>
          <EmptyState
            icon="◫"
            title="No projects yet"
            description={
              can('manager')
                ? 'Create a project to keep one survey round’s data and dashboards together, and to give people access to it alone.'
                : 'You have not been added to a project yet. Datasets and dashboards outside any project stay visible to everyone.'
            }
            action={
              can('manager') && (
                <button className="btn-primary btn-sm" onClick={() => setCreating(true)}>
                  Create a project
                </button>
              )
            }
          />
        </Card>
      ) : view === 'list' ? (
        <ProjectRows projects={shown} sort={sort} direction={direction} onSort={orderBy} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((project) => (
            <article key={project.id} className="card flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <Link
                  to={`/projects/${project.id}`}
                  className="text-base font-semibold text-ink-900 hover:text-brand-700"
                >
                  {project.name}
                </Link>
                <Badge tone={STATUS_TONE[project.status]}>{project.status}</Badge>
              </div>
              {project.description && (
                <p className="mt-1 line-clamp-2 text-sm text-ink-500">{project.description}</p>
              )}
              <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-ink-100 pt-3 text-center">
                {[
                  ['Datasets', project.dataset_count],
                  ['Dashboards', project.dashboard_count],
                  ['Members', project.member_count],
                ].map(([label, count]) => (
                  <div key={label as string}>
                    <dt className="text-[11px] uppercase tracking-wide text-ink-400">{label}</dt>
                    <dd className="text-sm font-semibold tabular-nums text-ink-800">
                      {formatNumber(count as number)}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 text-[11px] text-ink-400">
                {/* An administrator reaches every project regardless of membership,
                    so naming a role for them would misdescribe why they are here. */}
                {project.your_role && project.your_role !== 'admin'
                  ? `Your role: ${project.your_role}`
                  : 'Administrator access'}{' '}
                · updated {relativeTime(project.updated_at)}
              </p>
            </article>
          ))}
        </div>
      )}

      {creating && (
        <NewProjectModal
          onClose={() => setCreating(false)}
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ['projects'] })
            toast.push('Project created', 'success')
            setCreating(false)
          }}
        />
      )}
    </>
  )
}

/**
 * The same projects as rows: more of them on a screen, and comparable.
 *
 * Cards are better for recognising one project; a table is better for the
 * question a table answers, which is "which of these has no datasets in it
 * yet" or "which was touched last".
 */
function ProjectRows({
  projects,
  sort,
  direction,
  onSort,
}: {
  projects: Project[]
  sort: string
  direction: Direction
  onSort: (column: string, direction: Direction) => void
}) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-ink-200 text-xs uppercase tracking-wide text-ink-500 dark:border-dark-200 dark:text-dark-500">
          <tr>
            <SortHeader label="Project" column="name" sort={sort} direction={direction} onSort={onSort} />
            <SortHeader label="Status" column="status" sort={sort} direction={direction} onSort={onSort} />
            <SortHeader label="Datasets" column="datasets" sort={sort} direction={direction} onSort={onSort} align="right" />
            <SortHeader label="Dashboards" column="dashboards" sort={sort} direction={direction} onSort={onSort} align="right" />
            <SortHeader label="Members" column="members" sort={sort} direction={direction} onSort={onSort} align="right" />
            <SortHeader label="Updated" column="updated" sort={sort} direction={direction} onSort={onSort} />
            <th className="px-3 py-2 text-left font-medium">Your role</th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr
              key={project.id}
              className="border-b border-ink-100 last:border-0 hover:bg-ink-50 dark:border-dark-200 dark:hover:bg-dark-100"
            >
              <td className="px-3 py-2.5">
                <Link
                  to={`/projects/${project.id}`}
                  className="font-medium text-ink-900 hover:text-brand-700 dark:text-dark-900 dark:hover:text-brand-400"
                >
                  {project.name}
                </Link>
                {project.description && (
                  <p className="line-clamp-1 text-xs text-ink-500 dark:text-dark-500">
                    {project.description}
                  </p>
                )}
              </td>
              <td className="px-3 py-2.5">
                <Badge tone={STATUS_TONE[project.status]}>{project.status}</Badge>
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">
                {formatNumber(project.dataset_count)}
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">
                {formatNumber(project.dashboard_count)}
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">
                {formatNumber(project.member_count)}
              </td>
              <td className="whitespace-nowrap px-3 py-2.5 text-ink-500 dark:text-dark-500">
                {relativeTime(project.updated_at)}
              </td>
              <td className="px-3 py-2.5 text-ink-500 dark:text-dark-500">
                {project.your_role && project.your_role !== 'admin'
                  ? project.your_role
                  : 'Administrator'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function NewProjectModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const toast = useToast()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [startsOn, setStartsOn] = useState('')
  const [endsOn, setEndsOn] = useState('')

  const create = useMutation({
    mutationFn: () =>
      api.post<Project>('/projects', {
        name,
        description,
        starts_on: startsOn || null,
        ends_on: endsOn || null,
      }),
    onSuccess: onCreated,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title="New project"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => create.mutate()}
            disabled={!name.trim() || create.isPending}
          >
            Create
          </button>
        </>
      }
    >
      <Field label="Name">
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Round 1 fieldwork"
        />
      </Field>
      <Field label="Description" hint="What this project covers.">
        <textarea
          className="input"
          rows={2}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Starts on">
          <input
            type="date"
            className="input"
            value={startsOn}
            onChange={(event) => setStartsOn(event.target.value)}
          />
        </Field>
        <Field label="Ends on">
          <input
            type="date"
            className="input"
            value={endsOn}
            onChange={(event) => setEndsOn(event.target.value)}
          />
        </Field>
      </div>
      <p className="mt-1 text-xs text-ink-500">
        You are added as its manager, so it stays visible to you. Datasets and dashboards
        outside any project remain visible to everyone.
      </p>
    </Modal>
  )
}
