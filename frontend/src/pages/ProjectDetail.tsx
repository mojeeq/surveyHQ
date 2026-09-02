import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime } from '@/lib/format'
import type {
  Dashboard,
  Dataset,
  Page,
  Project,
  ProjectMember,
  Role,
  User,
} from '@/lib/types'
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

const PROJECT_ROLES: { value: Role; label: string; description: string }[] = [
  { value: 'viewer', label: 'Viewer', description: 'Read this project’s dashboards and data' },
  { value: 'analyst', label: 'Analyst', description: 'Build charts and dashboards here' },
  { value: 'manager', label: 'Manager', description: 'Manage this project and its members' },
]

export default function ProjectDetail() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'data' | 'members'>('data')

  const project = useQuery({
    queryKey: ['project', id],
    queryFn: () => api.get<Project>(`/projects/${id}`),
  })
  const datasets = useQuery({
    queryKey: ['datasets', { project: id }],
    queryFn: () => api.get<Page<Dataset>>(`/datasets?project_id=${id}&limit=200`),
  })
  const dashboards = useQuery({
    queryKey: ['dashboards', { project: id }],
    queryFn: () => api.get<Dashboard[]>(`/dashboards?project_id=${id}`),
  })

  // "manager" here is the role on this project, which is already capped by the
  // user's own role on the server, so this is the only check the UI needs.
  const canManage = project.data?.your_role === 'manager' || project.data?.your_role === 'admin'

  const remove = useMutation({
    mutationFn: () => api.delete(`/projects/${id}`),
    onSuccess: () => {
      toast.push('Project deleted; its data moved to the shared area', 'success')
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate('/projects')
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  if (project.isLoading) return <Loading />
  if (project.error) return <ErrorNote error={project.error} />
  if (!project.data) return null

  return (
    <>
      <PageHeader
        title={project.data.name}
        description={project.data.description || 'No description'}
        actions={
          <>
            <Badge tone={project.data.status === 'active' ? 'success' : 'neutral'}>
              {project.data.status}
            </Badge>
            {canManage && (
              <button
                className="btn-secondary text-red-600"
                onClick={() => {
                  if (
                    confirm(
                      `Delete "${project.data!.name}"? Its datasets and dashboards are kept ` +
                        'and moved to the shared area.',
                    )
                  )
                    remove.mutate()
                }}
              >
                Delete project
              </button>
            )}
          </>
        }
      />

      <Tabs
        tabs={[
          {
            id: 'data',
            label: 'Data & dashboards',
            count: (datasets.data?.items.length ?? 0) + (dashboards.data?.length ?? 0),
          },
          { id: 'members', label: 'Members', count: project.data.member_count },
        ]}
        active={tab}
        onChange={(next) => setTab(next as 'data' | 'members')}
      />

      {tab === 'data' ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card title="Datasets" subtitle="Available as a source for anything in this project">
            {datasets.isLoading ? (
              <Loading />
            ) : !datasets.data?.items.length ? (
              <EmptyState
                icon="▤"
                title="No datasets yet"
                description="Assign one from the Datasets page, or upload straight into this project."
              />
            ) : (
              <ul className="divide-y divide-ink-100">
                {datasets.data.items.map((dataset) => (
                  <li key={dataset.id} className="flex items-center justify-between gap-3 py-2.5">
                    <Link
                      to={`/datasets/${dataset.id}`}
                      className="text-sm font-medium text-ink-800 hover:text-brand-700"
                    >
                      {dataset.name}
                    </Link>
                    <span className="shrink-0 text-xs tabular-nums text-ink-400">
                      {formatNumber(dataset.row_count)} rows
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Dashboards">
            {dashboards.isLoading ? (
              <Loading />
            ) : !dashboards.data?.length ? (
              <EmptyState
                icon="▦"
                title="No dashboards yet"
                description="Create one from the Dashboards page and assign it here."
              />
            ) : (
              <ul className="divide-y divide-ink-100">
                {dashboards.data.map((dashboard) => (
                  <li key={dashboard.id} className="flex items-center justify-between gap-3 py-2.5">
                    <Link
                      to={`/dashboards/${dashboard.id}`}
                      className="text-sm font-medium text-ink-800 hover:text-brand-700"
                    >
                      {dashboard.name}
                    </Link>
                    <span className="shrink-0 text-xs text-ink-400">
                      {relativeTime(dashboard.updated_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      ) : (
        <Members projectId={id} members={project.data.members ?? []} canManage={canManage} />
      )}
    </>
  )
}

function Members({
  projectId,
  members,
  canManage,
}: {
  projectId: string
  members: ProjectMember[]
  canManage: boolean
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { can } = useAuth()
  const [adding, setAdding] = useState(false)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    queryClient.invalidateQueries({ queryKey: ['projects'] })
  }

  const setRole = useMutation({
    mutationFn: (payload: { user_id: string; role: Role }) =>
      api.put(`/projects/${projectId}/members`, payload),
    onSuccess: refresh,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })
  const remove = useMutation({
    mutationFn: (userId: string) => api.delete(`/projects/${projectId}/members/${userId}`),
    onSuccess: () => {
      toast.push('Member removed', 'success')
      refresh()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Card
      className="mt-4"
      title="Members"
      subtitle="A member’s role here never exceeds their own role on the platform."
      actions={
        canManage &&
        can('admin') && (
          <button className="btn-primary btn-sm" onClick={() => setAdding(true)}>
            Add member
          </button>
        )
      }
    >
      {!members.length ? (
        <EmptyState
          icon="◍"
          title="No members"
          description="Only administrators can reach this project until someone is added."
        />
      ) : (
        <ul className="divide-y divide-ink-100">
          {members.map((member) => (
            <li key={member.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink-800">
                  {member.full_name || member.email}
                </p>
                {member.full_name && (
                  <p className="truncate text-xs text-ink-400">{member.email}</p>
                )}
              </div>
              {canManage ? (
                <select
                  className="input w-32"
                  value={member.role}
                  onChange={(event) =>
                    setRole.mutate({ user_id: member.user_id, role: event.target.value as Role })
                  }
                >
                  {PROJECT_ROLES.map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              ) : (
                <Badge>{member.role}</Badge>
              )}
              {canManage && (
                <button
                  className="btn-ghost btn-sm text-red-600"
                  onClick={() => remove.mutate(member.user_id)}
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <AddMemberModal
          projectId={projectId}
          existing={members.map((m) => m.user_id)}
          onClose={() => setAdding(false)}
          onAdded={() => {
            toast.push('Member added', 'success')
            refresh()
            setAdding(false)
          }}
        />
      )}
    </Card>
  )
}

function AddMemberModal({
  projectId,
  existing,
  onClose,
  onAdded,
}: {
  projectId: string
  existing: string[]
  onClose: () => void
  onAdded: () => void
}) {
  const toast = useToast()
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState<Role>('viewer')

  // Listing users is an administrator-only endpoint, which is why adding a
  // member is offered only to administrators.
  const users = useQuery({
    queryKey: ['users'],
    queryFn: () => api.get<Page<User>>('/users?limit=200'),
  })
  const candidates = (users.data?.items ?? []).filter((u) => !existing.includes(u.id))

  const add = useMutation({
    mutationFn: () => api.put(`/projects/${projectId}/members`, { user_id: userId, role }),
    onSuccess: onAdded,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title="Add a member"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => add.mutate()} disabled={!userId}>
            Add
          </button>
        </>
      }
    >
      {users.isLoading ? (
        <Loading />
      ) : !candidates.length ? (
        <p className="text-sm text-ink-500">Every user is already a member of this project.</p>
      ) : (
        <>
          <Field label="User">
            <select
              className="input"
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
            >
              <option value="">Choose a user…</option>
              {candidates.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.full_name ? `${user.full_name} — ${user.email}` : user.email}
                  {user.restricted_to_projects ? ' (project-only)' : ''}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Role on this project"
            hint={PROJECT_ROLES.find((r) => r.value === role)?.description}
          >
            <select
              className="input"
              value={role}
              onChange={(event) => setRole(event.target.value as Role)}
            >
              {PROJECT_ROLES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
        </>
      )}
    </Modal>
  )
}
