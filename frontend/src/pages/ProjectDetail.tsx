import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime } from '@/lib/format'
import type {
  Cardinality,
  Dashboard,
  Dataset,
  Page,
  Project,
  ProjectMember,
  Relationship,
  Role,
  User,
} from '@/lib/types'
import RelationshipMap from '@/components/RelationshipMap'
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
  const [tab, setTab] = useState<'data' | 'model' | 'members'>('data')

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
  const relationships = useQuery({
    queryKey: ['relationships', id],
    queryFn: () => api.get<Relationship[]>(`/relationships?project_id=${id}`),
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
          { id: 'model', label: 'Relationships', count: relationships.data?.length },
          { id: 'members', label: 'Members', count: project.data.member_count },
        ]}
        active={tab}
        onChange={(next) => setTab(next as 'data' | 'model' | 'members')}
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
      ) : tab === 'model' ? (
        <RelationshipsTab
          projectId={id}
          datasets={datasets.data?.items ?? []}
          relationships={relationships.data ?? []}
          canManage={canManage}
        />
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

/**
 * The project's data model: which datasets link to which, and on what.
 *
 * Detection is offered rather than run automatically, because it writes
 * relationships and a user should be the one to ask for that. Detected links
 * are marked as such and stop being marked the moment they are corrected, so
 * running detection again never quietly reverts a decision.
 */
function RelationshipsTab({
  projectId,
  datasets,
  relationships,
  canManage,
}: {
  projectId: string
  datasets: Dataset[]
  relationships: Relationship[]
  canManage: boolean
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Relationship | null>(null)
  const [merging, setMerging] = useState<Relationship | null>(null)
  const [adding, setAdding] = useState(false)
  const [clearing, setClearing] = useState(false)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['relationships', projectId] })
    queryClient.invalidateQueries({ queryKey: ['datasets'] })
  }

  const detect = useMutation({
    mutationFn: () =>
      api.post<{ proposed: unknown[]; created: number }>(
        `/relationships/detect?project_id=${projectId}`,
      ),
    onSuccess: (result) => {
      toast.push(
        result.created
          ? `Found ${result.created} new relationship${result.created === 1 ? '' : 's'}`
          : 'No new relationships found',
        result.created ? 'success' : 'info',
      )
      refresh()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      api.patch(`/relationships/${id}`, patch),
    onSuccess: () => {
      refresh()
      setSelected(null)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/relationships/${id}`),
    onSuccess: () => {
      toast.push('Relationship removed', 'success')
      refresh()
      setSelected(null)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const clearAll = useMutation({
    mutationFn: (detectedOnly: boolean) =>
      api.post<{ detail: string }>(
        `/relationships/clear?project_id=${projectId}&detected_only=${detectedOnly}`,
      ),
    onSuccess: (result) => {
      toast.push(result.detail, 'success')
      refresh()
      setSelected(null)
      setClearing(false)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Card
      className="mt-4"
      title="Data model"
      subtitle="How this project's datasets link to each other"
      actions={
        canManage && (
          <>
            <button
              className="btn-secondary btn-sm"
              onClick={() => detect.mutate()}
              disabled={detect.isPending || datasets.length < 2}
            >
              {detect.isPending ? 'Looking…' : 'Detect'}
            </button>
            <button
              className="btn-secondary btn-sm"
              onClick={() => setAdding(true)}
              disabled={datasets.length < 2}
            >
              Add by hand
            </button>
            {relationships.length > 0 && (
              <button className="btn-ghost btn-sm text-red-600" onClick={() => setClearing(true)}>
                Clear
              </button>
            )}
          </>
        )
      }
    >
      {datasets.length < 2 ? (
        <EmptyState
          icon="◫"
          title="Not enough datasets to relate"
          description="A relationship links two datasets, so this needs at least two in the project."
        />
      ) : (
        <>
          <RelationshipMap
            datasets={datasets}
            relationships={relationships}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
          />

          {!relationships.length && (
            <p className="mt-4 text-sm text-ink-500">
              No relationships yet.{' '}
              {canManage
                ? 'Detect them from the data, or add one by hand.'
                : 'A project manager can detect them from the data.'}
            </p>
          )}

          {adding && (
            <ManualRelationshipModal
              datasets={datasets}
              onClose={() => setAdding(false)}
              onCreated={() => {
                refresh()
                setAdding(false)
              }}
            />
          )}

          {clearing && (
            <Modal
              open
              onClose={() => setClearing(false)}
              title="Clear relationships"
              footer={
                <>
                  <button className="btn-secondary" onClick={() => setClearing(false)}>
                    Cancel
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => clearAll.mutate(true)}
                    disabled={clearAll.isPending}
                  >
                    Only the detected ones
                  </button>
                  <button
                    className="btn-primary"
                    onClick={() => clearAll.mutate(false)}
                    disabled={clearAll.isPending}
                  >
                    Clear all {relationships.length}
                  </button>
                </>
              }
            >
              <p className="text-sm text-ink-600">
                Detection is a guess made from the data, and a wrong guess is easier to clear
                out than to correct one at a time. Datasets already merged keep their data —
                they hold their own copy — but they can no longer be re-run from a
                relationship that is gone.
              </p>
              <p className="mt-2 text-sm text-ink-600">
                {relationships.filter((r) => !r.detected).length} of these were made or
                corrected by hand.
              </p>
            </Modal>
          )}

          {selected && (
            <div className="mt-4 rounded-lg border border-brand-200 bg-brand-50 p-4">
              <p className="text-sm font-medium text-ink-900">
                {selected.left_name} → {selected.right_name}
              </p>
              <p className="mt-0.5 text-xs text-ink-600">
                Joined on <code>{selected.left_variable}</code> ={' '}
                <code>{selected.right_variable}</code>
              </p>

              {canManage && (
                <div className="mt-3 flex flex-wrap items-end gap-3">
                  <Field label="Cardinality">
                    <select
                      className="input w-44"
                      value={selected.cardinality}
                      onChange={(event) =>
                        update.mutate({
                          id: selected.id,
                          patch: { cardinality: event.target.value as Cardinality },
                        })
                      }
                    >
                      <option value="one_to_one">One to one</option>
                      <option value="one_to_many">One to many</option>
                      <option value="many_to_one">Many to one</option>
                      <option value="many_to_many">Many to many</option>
                    </select>
                  </Field>
                  <label className="mb-4 flex items-center gap-2 text-sm text-ink-700">
                    <input
                      type="checkbox"
                      checked={selected.is_active}
                      onChange={(event) =>
                        update.mutate({
                          id: selected.id,
                          patch: { is_active: event.target.checked },
                        })
                      }
                    />
                    Use for merging
                  </label>
                  <button
                    className="btn-primary btn-sm mb-4"
                    disabled={
                      !selected.is_active || selected.cardinality === 'many_to_many'
                    }
                    title={
                      selected.cardinality === 'many_to_many'
                        ? 'Joining these would multiply rows rather than add columns'
                        : undefined
                    }
                    onClick={() => setMerging(selected)}
                  >
                    Merge into a new dataset
                  </button>
                  <button
                    className="btn-ghost btn-sm mb-4 text-red-600"
                    onClick={() => {
                      if (confirm('Remove this relationship?')) remove.mutate(selected.id)
                    }}
                  >
                    Remove
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {merging && (
        <MergeModal
          relationship={merging}
          onClose={() => setMerging(null)}
          onDone={() => {
            refresh()
            setMerging(null)
          }}
        />
      )}
    </Card>
  )
}

function MergeModal({
  relationship,
  onClose,
  onDone,
}: {
  relationship: Relationship
  onClose: () => void
  onDone: () => void
}) {
  const toast = useToast()
  const [name, setName] = useState(
    `${relationship.left_name} + ${relationship.right_name}`,
  )
  const [how, setHow] = useState<'left' | 'inner'>('left')
  const [prefix, setPrefix] = useState('')

  const right = useQuery({
    queryKey: ['dataset', relationship.right_dataset_id],
    queryFn: () => api.get<Dataset>(`/datasets/${relationship.right_dataset_id}`),
  })
  const [columns, setColumns] = useState<string[]>([])

  const merge = useMutation({
    mutationFn: () =>
      api.post<Dataset>('/relationships/merge', {
        name,
        relationship_id: relationship.id,
        how,
        columns,
        prefix,
      }),
    onSuccess: (dataset) => {
      toast.push(`Created "${dataset.name}" with ${dataset.row_count} rows`, 'success')
      onDone()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const available = (right.data?.variables ?? []).filter(
    (v) => v.name !== relationship.right_variable && !v.is_hidden,
  )

  return (
    <Modal
      open
      onClose={onClose}
      title={`Merge ${relationship.right_name} into ${relationship.left_name}`}
      wide
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => merge.mutate()}
            disabled={!name.trim() || merge.isPending}
          >
            Create merged dataset
          </button>
        </>
      }
    >
      <Field label="Name">
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </Field>

      <Field
        label="Rows to keep"
        hint={
          how === 'left'
            ? `Every row of ${relationship.left_name}, whether or not it has a match.`
            : 'Only rows that match on both sides.'
        }
      >
        <select
          className="input"
          value={how}
          onChange={(event) => setHow(event.target.value as 'left' | 'inner')}
        >
          <option value="left">All of {relationship.left_name}</option>
          <option value="inner">Only matching rows</option>
        </select>
      </Field>

      <Field
        label="Prefix for the added columns"
        hint="Optional, e.g. “hh_”. A name that would clash gets “__right” either way."
      >
        <input
          className="input"
          value={prefix}
          onChange={(event) => setPrefix(event.target.value)}
          placeholder="none"
        />
      </Field>

      <Field
        label={`Columns to take from ${relationship.right_name}`}
        hint={
          columns.length
            ? `${columns.length} selected`
            : 'None selected means every column.'
        }
      >
        <div className="max-h-52 overflow-auto rounded-lg border border-ink-200 p-2">
          {available.map((variable) => (
            <label
              key={variable.name}
              className="flex items-center gap-2 py-0.5 text-sm text-ink-700"
            >
              <input
                type="checkbox"
                checked={columns.includes(variable.name)}
                onChange={(event) =>
                  setColumns(
                    event.target.checked
                      ? [...columns, variable.name]
                      : columns.filter((c) => c !== variable.name),
                  )
                }
              />
              <span className="truncate">
                {variable.label ? `${variable.name} — ${variable.label}` : variable.name}
              </span>
            </label>
          ))}
        </div>
      </Field>

      <p className="mt-2 text-xs text-ink-500">
        The merge is saved with the new dataset, so it can be re-run from the dataset
        page whenever either source is updated.
      </p>
    </Modal>
  )
}


/**
 * A relationship somebody knows about that detection did not find.
 *
 * Detection matches obvious keys - interview__id to interview__id, a name that
 * appears on both sides with enough values in common. It cannot know that this
 * survey's household id is called `hhid` on one file and `HH_SERIAL` on the
 * other, which is exactly the case the analyst can settle in ten seconds.
 */
function ManualRelationshipModal({
  datasets,
  onClose,
  onCreated,
}: {
  datasets: Dataset[]
  onClose: () => void
  onCreated: () => void
}) {
  const toast = useToast()
  const [leftId, setLeftId] = useState(datasets[0]?.id ?? '')
  const [rightId, setRightId] = useState(datasets[1]?.id ?? '')
  const [leftVariable, setLeftVariable] = useState('')
  const [rightVariable, setRightVariable] = useState('')
  const [cardinality, setCardinality] = useState('one_to_many')

  const left = useQuery({
    queryKey: ['dataset', leftId],
    queryFn: () => api.get<Dataset>(`/datasets/${leftId}`),
    enabled: Boolean(leftId),
  })
  const right = useQuery({
    queryKey: ['dataset', rightId],
    queryFn: () => api.get<Dataset>(`/datasets/${rightId}`),
    enabled: Boolean(rightId),
  })

  const create = useMutation({
    mutationFn: () =>
      api.post('/relationships', {
        left_dataset_id: leftId,
        right_dataset_id: rightId,
        left_variable: leftVariable,
        right_variable: rightVariable,
        cardinality,
      }),
    onSuccess: () => {
      toast.push('Relationship added', 'success')
      onCreated()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const columns = (dataset: Dataset | undefined) =>
    (dataset?.variables ?? []).filter((v) => !v.is_hidden)

  const ready = leftId && rightId && leftId !== rightId && leftVariable && rightVariable

  return (
    <Modal
      open
      onClose={onClose}
      title="Add a relationship"
      wide
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => create.mutate()}
            disabled={!ready || create.isPending}
          >
            Add relationship
          </button>
        </>
      }
    >
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="From dataset">
          <select
            className="input"
            value={leftId}
            onChange={(event) => {
              setLeftId(event.target.value)
              setLeftVariable('')
            }}
          >
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="To dataset">
          <select
            className="input"
            value={rightId}
            onChange={(event) => {
              setRightId(event.target.value)
              setRightVariable('')
            }}
          >
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Joined on">
          <select
            className="input"
            value={leftVariable}
            onChange={(event) => setLeftVariable(event.target.value)}
          >
            <option value="">Choose a column…</option>
            {columns(left.data).map((variable) => (
              <option key={variable.name} value={variable.name}>
                {variable.label ? `${variable.name} — ${variable.label}` : variable.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="equals">
          <select
            className="input"
            value={rightVariable}
            onChange={(event) => setRightVariable(event.target.value)}
          >
            <option value="">Choose a column…</option>
            {columns(right.data).map((variable) => (
              <option key={variable.name} value={variable.name}>
                {variable.label ? `${variable.name} — ${variable.label}` : variable.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field
        label="How they line up"
        hint="One-to-many is the usual shape: one interview, several people."
      >
        <select
          className="input"
          value={cardinality}
          onChange={(event) => setCardinality(event.target.value)}
        >
          <option value="one_to_one">One to one</option>
          <option value="one_to_many">One to many</option>
          <option value="many_to_one">Many to one</option>
          <option value="many_to_many">Many to many</option>
        </select>
      </Field>

      {leftId === rightId && (
        <p className="text-xs text-amber-700">A dataset cannot be related to itself.</p>
      )}
    </Modal>
  )
}
