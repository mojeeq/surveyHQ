import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime } from '@/lib/format'
import type { Project, ProjectStatus } from '@/lib/types'
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

const STATUS_TONE: Record<ProjectStatus, 'success' | 'warning' | 'neutral'> = {
  active: 'success',
  paused: 'warning',
  closed: 'neutral',
}

export default function Projects() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)

  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<Project[]>('/projects'),
  })

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

      {projects.isLoading ? (
        <Loading />
      ) : projects.error ? (
        <ErrorNote error={projects.error} retry={() => projects.refetch()} />
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
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.data.map((project) => (
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
