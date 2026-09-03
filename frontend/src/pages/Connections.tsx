import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, downloadFile } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { relativeTime } from '@/lib/format'
import type { Connection, Questionnaire, SyncRun } from '@/lib/types'
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
  Spinner,
  Toggle,
} from '@/components/ui'

const BLANK = {
  name: '',
  base_url: '',
  workspace: 'primary',
  username: '',
  password: '',
  verify_ssl: true,
  sync_enabled: false,
  sync_interval_minutes: 360,
  export_format: 'STATA' as const,
  questionnaires: [] as string[],
  interview_status: 'All',
  project_id: '',
}

export default function Connections() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Connection | null>(null)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState<Connection | null>(null)

  const connections = useQuery({
    queryKey: ['connections'],
    queryFn: () => api.get<Connection[]>('/connections'),
  })

  const test = useMutation({
    mutationFn: (id: string) =>
      api.post<{ ok: boolean; message: string }>(`/connections/${id}/test`),
    onSuccess: (result) => {
      toast.push(result.message, result.ok ? 'success' : 'error')
      queryClient.invalidateQueries({ queryKey: ['connections'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/connections/${id}`),
    onSuccess: () => {
      toast.push('Connection deleted', 'success')
      queryClient.invalidateQueries({ queryKey: ['connections'] })
    },
  })

  return (
    <>
      <PageHeader
        title="Survey Solutions connections"
        description="Link a headquarters server to import interview data automatically."
        actions={
          can('manager') && (
            <button className="btn-primary" onClick={() => setCreating(true)}>
              Add connection
            </button>
          )
        }
      />

      {connections.isLoading ? (
        <Loading />
      ) : connections.error ? (
        <ErrorNote error={connections.error} retry={connections.refetch} />
      ) : !connections.data?.length ? (
        <Card>
          <EmptyState
            icon="⇄"
            title="No servers connected"
            description="Connect your Survey Solutions headquarters server with an API user account to pull interview data on a schedule."
            action={
              can('manager') && (
                <button className="btn-primary btn-sm" onClick={() => setCreating(true)}>
                  Add your first connection
                </button>
              )
            }
          />
        </Card>
      ) : (
        <div className="space-y-4">
          {connections.data.map((connection) => (
            <Card
              key={connection.id}
              title={connection.name}
              subtitle={`${connection.base_url} · workspace "${connection.workspace}"`}
              actions={
                <>
                  <SyncBadge connection={connection} />
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => test.mutate(connection.id)}
                    disabled={test.isPending}
                  >
                    Test
                  </button>
                  {can('manager') && (
                    <>
                      <button
                        className="btn-primary btn-sm"
                        onClick={() => setImporting(connection)}
                      >
                        Import data
                      </button>
                      <button className="btn-ghost btn-sm" onClick={() => setEditing(connection)}>
                        Edit
                      </button>
                      <button
                        className="btn-ghost btn-sm text-red-600"
                        onClick={() => {
                          if (confirm(`Delete the connection "${connection.name}"?`))
                            remove.mutate(connection.id)
                        }}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </>
              }
            >
              <dl className="grid gap-4 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-xs uppercase text-ink-400">API user</dt>
                  <dd className="text-ink-700">{connection.username || 'not set'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-ink-400">Export format</dt>
                  <dd className="text-ink-700">{connection.export_format}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-ink-400">Scheduled sync</dt>
                  <dd className="text-ink-700">
                    {connection.sync_enabled
                      ? `every ${connection.sync_interval_minutes} min`
                      : 'off'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-ink-400">Last sync</dt>
                  <dd className="text-ink-700">{relativeTime(connection.last_sync_at)}</dd>
                </div>
              </dl>
              {connection.last_sync_error && (
                <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {connection.last_sync_error}
                </p>
              )}
              <SyncHistory connectionId={connection.id} />
            </Card>
          ))}
        </div>
      )}

      {(creating || editing) && (
        <ConnectionModal
          connection={editing}
          onClose={() => {
            setCreating(false)
            setEditing(null)
          }}
        />
      )}
      {importing && (
        <ImportModal connection={importing} onClose={() => setImporting(null)} />
      )}
    </>
  )
}

function SyncBadge({ connection }: { connection: Connection }) {
  const map = {
    success: { tone: 'success', icon: '✓', label: 'Synced' },
    failed: { tone: 'danger', icon: '⚠', label: 'Failed' },
    running: { tone: 'warning', icon: '◷', label: 'Running' },
    never: { tone: 'neutral', icon: '–', label: 'Never synced' },
  } as const
  const state = map[connection.last_sync_status]
  return (
    <Badge tone={state.tone} icon={state.icon}>
      {state.label}
    </Badge>
  )
}

function SyncHistory({ connectionId }: { connectionId: string }) {
  const runs = useQuery({
    queryKey: ['sync-runs', connectionId],
    queryFn: () => api.get<SyncRun[]>(`/connections/${connectionId}/runs?limit=5`),
    refetchInterval: 30_000,
  })
  if (!runs.data?.length) return null
  return (
    <div className="mt-4 border-t border-ink-100 pt-3">
      <p className="mb-2 text-xs font-semibold uppercase text-ink-400">Recent imports</p>
      <ul className="space-y-1.5">
        {runs.data.map((run) => (
          <li key={run.id} className="flex items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-2">
              <Badge
                tone={
                  run.status === 'success' ? 'success' : run.status === 'failed' ? 'danger' : 'warning'
                }
              >
                {run.status}
              </Badge>
              <span className="text-ink-700">{run.questionnaire}</span>
            </span>
            <span className="truncate text-ink-500">{run.message}</span>
            <span className="flex shrink-0 items-center gap-2">
              {run.has_archive && (
                <button
                  className="text-brand-600 hover:underline"
                  title="Download the export exactly as the server sent it"
                  onClick={() =>
                    downloadFile(
                      `/connections/${connectionId}/runs/${run.id}/archive`,
                      undefined,
                      `${run.questionnaire || 'export'}.zip`,
                      'GET',
                    )
                  }
                >
                  Download zip
                </button>
              )}
              <span className="text-ink-400">{relativeTime(run.started_at)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ConnectionModal({
  connection,
  onClose,
}: {
  connection: Connection | null
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    ...BLANK,
    ...(connection
      ? {
          name: connection.name,
          base_url: connection.base_url,
          workspace: connection.workspace,
          username: connection.username,
          password: '',
          verify_ssl: connection.verify_ssl,
          sync_enabled: connection.sync_enabled,
          sync_interval_minutes: connection.sync_interval_minutes,
          export_format: connection.export_format,
          questionnaires: connection.questionnaires,
          interview_status: connection.interview_status,
          project_id: connection.project_id ?? '',
        }
      : {}),
  })
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const update = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })

  const testUnsaved = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>('/connections/test', form),
    onSuccess: setTestResult,
    onError: (error: Error) => setTestResult({ ok: false, message: error.message }),
  })

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = { ...form, project_id: form.project_id || null }
      if (connection && !form.password) delete payload.password
      return connection
        ? api.patch(`/connections/${connection.id}`, payload)
        : api.post('/connections', payload)
    },
    onSuccess: () => {
      toast.push(connection ? 'Connection updated' : 'Connection created', 'success')
      queryClient.invalidateQueries({ queryKey: ['connections'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title={connection ? 'Edit connection' : 'Add Survey Solutions connection'}
      wide
      footer={
        <>
          <button
            className="btn-secondary mr-auto"
            onClick={() => testUnsaved.mutate()}
            disabled={testUnsaved.isPending}
          >
            {testUnsaved.isPending && <Spinner className="h-4 w-4" />}
            Test connection
          </button>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Spinner className="h-4 w-4 text-white" />}
            Save
          </button>
        </>
      }
    >
      {testResult && (
        <div
          className={`mb-4 rounded-lg border px-3 py-2 text-sm ${
            testResult.ok
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
              : 'border-red-200 bg-red-50 text-red-800'
          }`}
        >
          {testResult.message}
        </div>
      )}

      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="Connection name">
          <input
            className="input"
            value={form.name}
            onChange={(event) => update({ name: event.target.value })}
            placeholder="National Household Survey"
          />
        </Field>
        <Field label="Server URL" hint="The site root, e.g. https://demo.mysurvey.solutions">
          <input
            className="input"
            value={form.base_url}
            onChange={(event) => update({ base_url: event.target.value })}
            placeholder="https://your-server.mysurvey.solutions"
          />
        </Field>
        <Field label="Workspace" hint="Usually 'primary'">
          <input
            className="input"
            value={form.workspace}
            onChange={(event) => update({ workspace: event.target.value })}
          />
        </Field>
        <Field label="API user name" hint="A headquarters or API user on that workspace">
          <input
            className="input"
            value={form.username}
            onChange={(event) => update({ username: event.target.value })}
          />
        </Field>
        <Field
          label="Password"
          hint={connection ? 'Leave blank to keep the stored password' : 'Encrypted at rest'}
        >
          <input
            className="input"
            type="password"
            value={form.password}
            onChange={(event) => update({ password: event.target.value })}
          />
        </Field>
        <Field label="Export format">
          <select
            className="input"
            value={form.export_format}
            onChange={(event) =>
              update({ export_format: event.target.value as typeof form.export_format })
            }
          >
            <option value="STATA">Stata (.dta) — keeps value labels</option>
            <option value="Tabular">Tab-delimited</option>
            <option value="SPSS">SPSS (.sav)</option>
          </select>
        </Field>
        <ProjectPicker
          value={form.project_id}
          onChange={(project_id) => update({ project_id })}
          label="Default project for imports"
          hint="Where this server's data lands. A single import can be sent elsewhere."
        />

        <Field label="Interview status to import">
          <select
            className="input"
            value={form.interview_status}
            onChange={(event) => update({ interview_status: event.target.value })}
          >
            {[
              'All',
              'Completed',
              'ApprovedBySupervisor',
              'ApprovedByHeadquarters',
              'RejectedBySupervisor',
              'InterviewerAssigned',
            ].map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Sync interval (minutes)">
          <input
            className="input"
            type="number"
            min={5}
            value={form.sync_interval_minutes}
            onChange={(event) => update({ sync_interval_minutes: Number(event.target.value) })}
          />
        </Field>
      </div>

      <div className="space-y-3 border-t border-ink-200 pt-4">
        <Toggle
          checked={form.sync_enabled}
          onChange={(value) => update({ sync_enabled: value })}
          label="Import automatically on the schedule above"
        />
        <Toggle
          checked={form.verify_ssl}
          onChange={(value) => update({ verify_ssl: value })}
          label="Verify the server's TLS certificate (recommended)"
        />
      </div>
    </Modal>
  )
}

function ImportModal({ connection, onClose }: { connection: Connection; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[]>(connection.questionnaires)
  const [projectId, setProjectId] = useState(connection.project_id ?? '')
  const [mode, setMode] = useState<'replace' | 'append'>('replace')

  const questionnaires = useQuery({
    queryKey: ['questionnaires', connection.id],
    queryFn: () => api.get<Questionnaire[]>(`/connections/${connection.id}/questionnaires`),
  })

  const start = useMutation({
    mutationFn: () =>
      api.post(`/connections/${connection.id}/sync`, {
        questionnaires: selected,
        project_id: projectId || null,
        mode,
      }),
    onSuccess: () => {
      toast.push(
        'Import started. It runs in the background and can take a few minutes for large surveys.',
        'success',
      )
      queryClient.invalidateQueries({ queryKey: ['sync-runs'] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title={`Import from ${connection.name}`}
      wide
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => start.mutate()}
            disabled={!selected.length || start.isPending}
          >
            {start.isPending && <Spinner className="h-4 w-4 text-white" />}
            Import {selected.length} questionnaire{selected.length === 1 ? '' : 's'}
          </button>
        </>
      }
    >
      <div className="mb-4 grid gap-x-4 sm:grid-cols-2">
        <ProjectPicker
          value={projectId}
          onChange={setProjectId}
          label="Import into project"
        />
        <Field
          label="If these datasets already exist"
          hint="Replacing keeps the datasets' ids, so charts, indicators and merges built on them go on working."
        >
          <select
            className="input"
            value={mode}
            onChange={(event) => setMode(event.target.value as 'replace' | 'append')}
          >
            <option value="replace">Replace their data</option>
            <option value="append">Add these rows to them</option>
          </select>
        </Field>
      </div>

      {questionnaires.isLoading ? (
        <Loading label="Fetching questionnaires from the server" />
      ) : questionnaires.error ? (
        <ErrorNote error={questionnaires.error} retry={questionnaires.refetch} />
      ) : !questionnaires.data?.length ? (
        <EmptyState
          icon="◌"
          title="No questionnaires visible"
          description="The API user may not have access to any questionnaires in this workspace."
        />
      ) : (
        <>
          <p className="mb-3 text-sm text-ink-500">
            Each questionnaire's whole export is imported - one dataset per roster level, with
            the paradata - and re-importing refreshes them in place, so saved
            charts and indicators keep working.
          </p>
          <div className="max-h-80 space-y-1 overflow-y-auto">
            {questionnaires.data.map((questionnaire) => (
              <label
                key={questionnaire.identity}
                className="flex cursor-pointer items-center gap-3 rounded-lg border border-ink-200 px-3 py-2.5 hover:bg-ink-50"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(questionnaire.identity)}
                  onChange={(event) =>
                    setSelected(
                      event.target.checked
                        ? [...selected, questionnaire.identity]
                        : selected.filter((id) => id !== questionnaire.identity),
                    )
                  }
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink-800">
                    {questionnaire.title}
                  </p>
                  <p className="text-xs text-ink-500">
                    Version {questionnaire.version}
                    {questionnaire.variable && ` · ${questionnaire.variable}`}
                  </p>
                </div>
              </label>
            ))}
          </div>
        </>
      )}
    </Modal>
  )
}
