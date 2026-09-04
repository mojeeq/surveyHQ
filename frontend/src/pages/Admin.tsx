import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatDate, relativeTime } from '@/lib/format'
import type { ApiKeyOut, Job, Page, Role, User } from '@/lib/types'
import {
  Badge,
  Card,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Tabs,
} from '@/components/ui'

const ROLES: { value: Role; label: string; description: string }[] = [
  { value: 'viewer', label: 'Viewer', description: 'Read dashboards only' },
  { value: 'analyst', label: 'Analyst', description: 'Build charts and dashboards' },
  { value: 'manager', label: 'Manager', description: 'Manage data, connections and monitoring' },
  { value: 'admin', label: 'Administrator', description: 'Everything, including users' },
]

export default function Admin() {
  const [tab, setTab] = useState<'users' | 'jobs' | 'keys' | 'audit'>('users')
  return (
    <>
      <PageHeader title="Administration" description="Users, background jobs and access." />
      <Tabs
        tabs={[
          { id: 'users', label: 'Users' },
          { id: 'jobs', label: 'Background jobs' },
          { id: 'keys', label: 'API keys' },
          { id: 'audit', label: 'Audit log' },
        ]}
        active={tab}
        onChange={setTab}
      />
      <div className="mt-4">
        {tab === 'users' && <Users />}
        {tab === 'jobs' && <Jobs />}
        {tab === 'keys' && <ApiKeys />}
        {tab === 'audit' && <AuditLog />}
      </div>
    </>
  )
}

function Users() {
  const toast = useToast()
  const { user: me } = useAuth()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    email: '',
    full_name: '',
    role: 'viewer' as Role,
    restricted_to_projects: false,
    password: '',
  })

  const users = useQuery({
    queryKey: ['users'],
    queryFn: () => api.get<Page<User>>('/users?limit=200'),
  })

  const create = useMutation({
    mutationFn: () => api.post('/users', form),
    onSuccess: () => {
      toast.push('User created', 'success')
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setCreating(false)
      setForm({
        email: '',
        full_name: '',
        role: 'viewer',
        restricted_to_projects: false,
        password: '',
      })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      api.patch(`/users/${id}`, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/users/${id}`),
    onSuccess: () => {
      toast.push('User deleted', 'success')
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  if (users.isLoading) return <Loading />
  if (users.error) return <ErrorNote error={users.error} />

  return (
    <Card
      title="Users"
      actions={
        <button className="btn-primary btn-sm" onClick={() => setCreating(true)}>
          Add user
        </button>
      }
      bodyClassName="p-0"
    >
      <table className="table-base">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            <th>Access</th>
            <th>Status</th>
            <th>Last sign in</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.data!.items.map((user) => (
            <tr key={user.id}>
              <td className="font-medium">{user.full_name || '–'}</td>
              <td className="text-ink-600">{user.email}</td>
              <td>
                <select
                  className="input w-32 py-1 text-xs"
                  value={user.role}
                  disabled={user.id === me?.id}
                  onChange={(event) =>
                    update.mutate({ id: user.id, patch: { role: event.target.value } })
                  }
                >
                  {ROLES.map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <label className="flex items-center gap-1.5 text-xs text-ink-600">
                  <input
                    type="checkbox"
                    checked={user.restricted_to_projects}
                    disabled={user.id === me?.id || user.role === 'admin'}
                    onChange={(event) =>
                      update.mutate({
                        id: user.id,
                        patch: { restricted_to_projects: event.target.checked },
                      })
                    }
                  />
                  {/* An administrator sees everything regardless, so saying
                      "assigned projects only" of one would be a lie. */}
                  {user.role === 'admin' ? 'Everything' : 'Assigned projects only'}
                </label>
              </td>
              <td>
                {user.is_active ? (
                  <Badge tone="success" icon="✓">
                    Active
                  </Badge>
                ) : (
                  <Badge tone="neutral">Disabled</Badge>
                )}
              </td>
              <td className="text-xs text-ink-500">{relativeTime(user.last_login_at)}</td>
              <td className="text-right">
                {user.id !== me?.id && (
                  <>
                    <button
                      className="btn-ghost btn-sm"
                      onClick={() =>
                        update.mutate({ id: user.id, patch: { is_active: !user.is_active } })
                      }
                    >
                      {user.is_active ? 'Disable' : 'Enable'}
                    </button>
                    <button
                      className="btn-ghost btn-sm text-red-600"
                      onClick={() => {
                        if (confirm(`Delete ${user.email}?`)) remove.mutate(user.id)
                      }}
                    >
                      Delete
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="Add a user"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setCreating(false)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => create.mutate()}
              disabled={!form.email || form.password.length < 8}
            >
              Create user
            </button>
          </>
        }
      >
        <Field label="Email">
          <input
            className="input"
            type="email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
          />
        </Field>
        <Field label="Full name">
          <input
            className="input"
            value={form.full_name}
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
          />
        </Field>
        <Field label="Role" hint={ROLES.find((r) => r.value === form.role)?.description}>
          <select
            className="input"
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
          >
            {ROLES.map((role) => (
              <option key={role.value} value={role.value}>
                {role.label}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Access"
          hint="Use this for someone who should see one project and nothing else."
        >
          <label className="flex items-start gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={form.restricted_to_projects}
              disabled={form.role === 'admin'}
              onChange={(event) =>
                setForm({ ...form, restricted_to_projects: event.target.checked })
              }
            />
            <span>
              Limit to assigned projects
              <span className="block text-xs text-ink-500">
                {form.role === 'admin'
                  ? 'Administrators always see everything.'
                  : 'Hides the shared area, leaving only projects this user is a member of. Add them to a project after creating the account.'}
              </span>
            </span>
          </label>
        </Field>
        <Field label="Password" hint="At least 8 characters">
          <input
            className="input"
            type="password"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
          />
        </Field>
      </Modal>
    </Card>
  )
}

function Jobs() {
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api.get<Job[]>('/system/jobs?limit=50'),
    refetchInterval: 10_000,
  })
  if (jobs.isLoading) return <Loading />
  return (
    <Card title="Background jobs" subtitle="Imports and scheduled work" bodyClassName="p-0">
      <table className="table-base">
        <thead>
          <tr>
            <th>Job</th>
            <th>Type</th>
            <th>Status</th>
            <th>Started</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {(jobs.data ?? []).map((job) => (
            <tr key={job.id}>
              <td className="font-medium">{job.title}</td>
              <td className="text-ink-600">{job.job_type}</td>
              <td>
                <Badge
                  tone={
                    job.status === 'success'
                      ? 'success'
                      : job.status === 'failed'
                        ? 'danger'
                        : job.status === 'running'
                          ? 'warning'
                          : 'neutral'
                  }
                >
                  {job.status}
                </Badge>
              </td>
              <td className="text-xs text-ink-500">{relativeTime(job.started_at ?? job.created_at)}</td>
              <td className="max-w-md truncate text-xs text-ink-600">
                {job.error || JSON.stringify(job.result ?? {})}
              </td>
            </tr>
          ))}
          {!jobs.data?.length && (
            <tr>
              <td colSpan={5} className="py-8 text-center text-sm text-ink-500">
                No jobs have run yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  )
}

function ApiKeys() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [created, setCreated] = useState<string | null>(null)
  const [name, setName] = useState('')

  const keys = useQuery({
    queryKey: ['api-keys'],
    queryFn: () => api.get<ApiKeyOut[]>('/auth/api-keys'),
  })

  const create = useMutation({
    mutationFn: () => api.post<ApiKeyOut & { key: string }>('/auth/api-keys', { name }),
    onSuccess: (result) => {
      setCreated(result.key)
      setName('')
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  const revoke = useMutation({
    mutationFn: (id: string) => api.delete(`/auth/api-keys/${id}`),
    onSuccess: () => {
      toast.push('API key revoked', 'success')
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  return (
    <Card
      title="API keys"
      subtitle="For scripts and integrations. Send as the X-API-Key header."
    >
      {created && (
        <div className="mb-4 rounded-card border border-emerald-200 bg-emerald-50 p-3">
          <p className="text-sm font-medium text-emerald-900">
            Copy this key now. It is not shown again.
          </p>
          <code className="mt-2 block break-all rounded bg-white px-2 py-1.5 text-xs">
            {created}
          </code>
          <button className="btn-ghost btn-sm mt-1" onClick={() => setCreated(null)}>
            Done
          </button>
        </div>
      )}

      <div className="mb-4 flex gap-2">
        <input
          className="input max-w-xs"
          placeholder="Key name, e.g. reporting script"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <button className="btn-primary" onClick={() => create.mutate()}>
          Create key
        </button>
      </div>

      <table className="table-base">
        <thead>
          <tr>
            <th>Name</th>
            <th>Prefix</th>
            <th>Created</th>
            <th>Last used</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(keys.data ?? []).map((key) => (
            <tr key={key.id}>
              <td className="font-medium">{key.name}</td>
              <td className="font-mono text-xs">shq_{key.prefix}…</td>
              <td className="text-xs text-ink-500">{formatDate(key.created_at)}</td>
              <td className="text-xs text-ink-500">{relativeTime(key.last_used_at)}</td>
              <td className="text-right">
                {key.revoked ? (
                  <Badge>revoked</Badge>
                ) : (
                  <button
                    className="btn-ghost btn-sm text-red-600"
                    onClick={() => revoke.mutate(key.id)}
                  >
                    Revoke
                  </button>
                )}
              </td>
            </tr>
          ))}
          {!keys.data?.length && (
            <tr>
              <td colSpan={5} className="py-8 text-center text-sm text-ink-500">
                No API keys yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  )
}

function AuditLog() {
  const audit = useQuery({
    queryKey: ['audit'],
    queryFn: () => api.get<Page<any>>('/system/audit?limit=200'),
  })
  if (audit.isLoading) return <Loading />
  if (audit.error) return <ErrorNote error={audit.error} />
  return (
    <Card title="Audit log" subtitle="Who did what, and when" bodyClassName="p-0">
      <div className="max-h-[600px] overflow-auto">
        <table className="table-base">
          <thead className="sticky top-0">
            <tr>
              <th>When</th>
              <th>User</th>
              <th>Action</th>
              <th>Entity</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {audit.data!.items.map((entry) => (
              <tr key={entry.id}>
                <td className="whitespace-nowrap text-xs text-ink-500">
                  {formatDate(entry.created_at, true)}
                </td>
                <td className="text-ink-700">{entry.user_email || 'system'}</td>
                <td>
                  <code className="text-xs">{entry.action}</code>
                </td>
                <td className="text-xs text-ink-500">
                  {entry.entity_type} {entry.entity_id?.slice(0, 8)}
                </td>
                <td className="max-w-md truncate text-xs text-ink-500">
                  {JSON.stringify(entry.detail)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
