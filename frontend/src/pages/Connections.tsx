import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, downloadFile } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { relativeTime } from '@/lib/format'
import type { Connection, Questionnaire, SyncRun } from '@/lib/types'
import ProjectPicker from '@/components/ProjectPicker'
import QuestionnairePicker, { describeSelection } from '@/components/QuestionnairePicker'
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

type SourceType =
  | 'survey_solutions'
  | 'odk'
  | 'kobo'
  | 'csweb'
  | 'surveycto'
  | 'sdmx'

type SourceConnection = Connection & {
  source_type?: SourceType
  source_config?: Record<string, unknown>
}

type RemoteResource = Questionnaire & {
  kind?: string
  meta?: Record<string, unknown>
}

const SOURCES: Record<
  SourceType,
  { label: string; description: string; urlHint: string; workspace?: string }
> = {
  survey_solutions: {
    label: 'Survey Solutions',
    description: 'World Bank CAPI headquarters exports, rosters and paradata',
    urlHint: 'https://your-server.mysurvey.solutions',
    workspace: 'Workspace',
  },
  odk: {
    label: 'ODK Central',
    description: 'ODK forms, submissions and repeat groups through Central OData',
    urlHint: 'https://central.example.org',
    workspace: 'ODK project ID',
  },
  kobo: {
    label: 'KoboToolbox',
    description: 'Kobo survey assets and submissions through the v2 API',
    urlHint: 'https://kf.kobotoolbox.org',
  },
  csweb: {
    label: 'CSPro / CSWeb',
    description: 'CSPro dictionaries and cases synchronised through CSWeb',
    urlHint: 'https://example.org/csweb/api',
  },
  surveycto: {
    label: 'SurveyCTO',
    description: 'SurveyCTO forms and wide JSON submission data',
    urlHint: 'https://your-server.surveycto.com',
  },
  sdmx: {
    label: 'SDMX API',
    description: 'Published official-statistics data from an SDMX REST endpoint',
    urlHint: 'https://api.example.org/public/rest/v1',
  },
}

const ZONES: string[] = (() => {
  const here = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  try {
    const all = (Intl as any).supportedValuesOf?.('timeZone') as string[] | undefined
    if (all?.length) return all
  } catch {
    /* fall through to the short list */
  }
  return [...new Set([here, 'UTC'])]
})()

const BLANK = {
  name: '',
  base_url: '',
  source_type: 'survey_solutions' as SourceType,
  source_config: {} as Record<string, unknown>,
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
  sync_mode: 'interval' as 'interval' | 'daily',
  sync_times: [] as string[],
  sync_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
}

function sourceOf(connection: SourceConnection): SourceType {
  return connection.source_type ?? 'survey_solutions'
}

function sourceName(connection: SourceConnection): string {
  return SOURCES[sourceOf(connection)].label
}

function resourceWord(source: SourceType, plural = false): string {
  const word =
    source === 'survey_solutions'
      ? 'questionnaire'
      : source === 'csweb'
        ? 'dictionary'
        : source === 'sdmx'
          ? 'data query'
          : 'form'
  return plural ? `${word}s` : word
}

export default function Connections() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<SourceConnection | null>(null)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState<SourceConnection | null>(null)

  const connections = useQuery({
    queryKey: ['connections'],
    queryFn: () => api.get<SourceConnection[]>('/connections'),
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
        title="Data connections"
        description="Bring survey microdata and published statistics into SurveyHQ on a schedule."
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
            title="No data sources connected"
            description="Connect Survey Solutions, ODK Central, KoboToolbox, CSWeb, SurveyCTO or an SDMX REST API."
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
          {connections.data.map((connection) => {
            const source = sourceOf(connection)
            const workspace = SOURCES[source].workspace
            return (
              <Card
                key={connection.id}
                title={connection.name}
                subtitle={`${sourceName(connection)} · ${connection.base_url}${
                  workspace && connection.workspace ? ` · ${connection.workspace}` : ''
                }`}
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
                        <button
                          className="btn-ghost btn-sm"
                          onClick={() => setEditing(connection)}
                        >
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
                    <dt className="text-xs uppercase text-ink-400">Source</dt>
                    <dd className="text-ink-700">{SOURCES[source].label}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-ink-400">Account</dt>
                    <dd className="text-ink-700">
                      {source === 'kobo'
                        ? connection.has_password
                          ? 'API token stored'
                          : 'token not set'
                        : source === 'sdmx' && !connection.username
                          ? 'public endpoint'
                          : connection.username || 'not set'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-ink-400">Scheduled sync</dt>
                    <dd className="text-ink-700">
                      {connection.sync_enabled
                        ? connection.sync_mode === 'daily'
                          ? connection.sync_times.join(', ') || 'daily'
                          : `every ${connection.sync_interval_minutes} min`
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
            )
          })}
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
    never: { tone: 'neutral', icon: '-', label: 'Never synced' },
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
                  run.status === 'success'
                    ? 'success'
                    : run.status === 'failed'
                      ? 'danger'
                      : 'warning'
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
  connection: SourceConnection | null
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const existingSource = connection ? sourceOf(connection) : BLANK.source_type
  const [form, setForm] = useState({
    ...BLANK,
    ...(connection
      ? {
          name: connection.name,
          base_url: connection.base_url,
          source_type: existingSource,
          source_config: connection.source_config ?? {},
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
          sync_mode: connection.sync_mode ?? 'interval',
          sync_times: connection.sync_times ?? [],
          sync_timezone: connection.sync_timezone || 'UTC',
        }
      : {}),
  })
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const update = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const source = SOURCES[form.source_type]

  const testUnsaved = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>('/connections/test', form),
    onSuccess: setTestResult,
    onError: (error: Error) => setTestResult({ ok: false, message: error.message }),
  })

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        ...form,
        project_id: form.project_id || null,
      }
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

  const sdmxResources = ((form.source_config.resources as unknown[]) ?? [])
    .map((item) => (typeof item === 'string' ? item : String((item as any)?.path ?? '')))
    .filter(Boolean)
    .join('\n')

  const setSdmxResources = (text: string) => {
    const paths = text
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter(Boolean)
    update({
      questionnaires: paths,
      source_config: { ...form.source_config, resources: paths },
    })
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={connection ? 'Edit data connection' : 'Add data connection'}
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
          className={`mb-4 rounded-card border px-3 py-2 text-sm ${
            testResult.ok
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
              : 'border-red-200 bg-red-50 text-red-800'
          }`}
        >
          {testResult.message}
        </div>
      )}

      <Field label="Source platform">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {(Object.entries(SOURCES) as [SourceType, (typeof SOURCES)[SourceType]][]).map(
            ([value, option]) => (
              <button
                key={value}
                type="button"
                className={`rounded-card border p-3 text-left transition ${
                  form.source_type === value
                    ? 'border-brand-500 bg-brand-50 ring-1 ring-brand-500'
                    : 'border-ink-200 bg-white hover:border-brand-300'
                }`}
                onClick={() =>
                  update({
                    source_type: value,
                    workspace: value === 'survey_solutions' ? 'primary' : '',
                    questionnaires: [],
                    source_config: {},
                    username: '',
                    password: '',
                  })
                }
              >
                <span className="block text-sm font-semibold text-ink-900">{option.label}</span>
                <span className="mt-1 block text-xs leading-5 text-ink-500">
                  {option.description}
                </span>
              </button>
            ),
          )}
        </div>
      </Field>

      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="Connection name">
          <input
            className="input"
            value={form.name}
            onChange={(event) => update({ name: event.target.value })}
            placeholder={`${source.label} connection`}
          />
        </Field>
        <Field label="Server / API URL" hint={source.urlHint}>
          <input
            className="input"
            value={form.base_url}
            onChange={(event) => update({ base_url: event.target.value })}
            placeholder={source.urlHint}
          />
        </Field>

        {source.workspace && (
          <Field
            label={source.workspace}
            hint={
              form.source_type === 'survey_solutions'
                ? "Usually 'primary'"
                : 'The numeric project id shown by ODK Central'
            }
          >
            <input
              className="input"
              value={form.workspace}
              onChange={(event) => update({ workspace: event.target.value })}
            />
          </Field>
        )}

        {form.source_type !== 'kobo' && (
          <Field
            label={form.source_type === 'odk' ? 'Central email / username' : 'API user name'}
            hint={form.source_type === 'sdmx' ? 'Optional for a protected SDMX endpoint' : undefined}
          >
            <input
              className="input"
              value={form.username}
              onChange={(event) => update({ username: event.target.value })}
            />
          </Field>
        )}

        <Field
          label={form.source_type === 'kobo' ? 'API token' : 'Password'}
          hint={
            connection
              ? `Leave blank to keep the stored ${form.source_type === 'kobo' ? 'token' : 'password'}`
              : form.source_type === 'sdmx'
                ? 'Optional for a public endpoint'
                : 'Encrypted at rest'
          }
        >
          <input
            className="input"
            type="password"
            value={form.password}
            onChange={(event) => update({ password: event.target.value })}
          />
        </Field>

        {form.source_type === 'survey_solutions' && (
          <>
            <Field label="Export format">
              <select
                className="input"
                value={form.export_format}
                onChange={(event) =>
                  update({ export_format: event.target.value as typeof form.export_format })
                }
              >
                <option value="STATA">Stata (.dta) - keeps value labels</option>
                <option value="Tabular">Tab-delimited</option>
                <option value="SPSS">SPSS (.sav)</option>
              </select>
            </Field>
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
          </>
        )}

        {form.source_type === 'surveycto' && (
          <Field label="Review status" hint="Which SurveyCTO submissions the API should return.">
            <select
              className="input"
              value={String(form.source_config.review_status ?? 'approved')}
              onChange={(event) =>
                update({
                  source_config: {
                    ...form.source_config,
                    review_status: event.target.value,
                  },
                })
              }
            >
              <option value="approved">Approved</option>
              <option value="pending">Pending</option>
              <option value="rejected">Rejected</option>
              <option value="all">All</option>
            </select>
          </Field>
        )}

        <ProjectPicker
          value={form.project_id}
          onChange={(project_id) => update({ project_id })}
          label="Default project for imports"
          hint="Where this connection's datasets land."
        />

        <Field label="Import automatically">
          <select
            className="input"
            value={form.sync_mode}
            onChange={(event) =>
              update({ sync_mode: event.target.value as 'interval' | 'daily' })
            }
          >
            <option value="interval">Every so many minutes</option>
            <option value="daily">At set times of day</option>
          </select>
        </Field>

        {form.sync_mode === 'interval' ? (
          <Field label="Sync interval (minutes)">
            <input
              className="input"
              type="number"
              min={5}
              value={form.sync_interval_minutes}
              onChange={(event) => update({ sync_interval_minutes: Number(event.target.value) })}
            />
          </Field>
        ) : (
          <Field label="Time zone" hint="The times below are read in this zone.">
            <select
              className="input"
              value={form.sync_timezone}
              onChange={(event) => update({ sync_timezone: event.target.value })}
            >
              {ZONES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>

      {form.source_type === 'sdmx' && (
        <Field
          label="SDMX data query paths"
          hint="One REST data path per line, relative to the API URL. Example: data/DF_LFS/.FJ...."
        >
          <textarea
            className="input min-h-28 font-mono text-xs"
            value={sdmxResources}
            onChange={(event) => setSdmxResources(event.target.value)}
            placeholder={'data/DF_POP/.FJ....\ndata/DF_LABOUR/.FJ....'}
          />
        </Field>
      )}

      {form.sync_mode === 'daily' && (
        <Field
          label="Import at"
          hint="24-hour times. Imports begin shortly after each time in the selected zone."
        >
          <div className="flex flex-wrap items-center gap-2">
            {form.sync_times.map((time, index) => (
              <span key={index} className="flex items-center gap-1">
                <input
                  className="input w-28"
                  type="time"
                  value={time}
                  onChange={(event) =>
                    update({
                      sync_times: form.sync_times.map((existing, i) =>
                        i === index ? event.target.value : existing,
                      ),
                    })
                  }
                />
                <button
                  className="btn-ghost btn-sm text-red-600"
                  aria-label={`Remove ${time}`}
                  onClick={() =>
                    update({ sync_times: form.sync_times.filter((_, i) => i !== index) })
                  }
                >
                  ✕
                </button>
              </span>
            ))}
            <button
              className="btn-secondary btn-sm"
              onClick={() => update({ sync_times: [...form.sync_times, '06:00'] })}
            >
              + Add a time
            </button>
          </div>
        </Field>
      )}

      {form.source_type !== 'sdmx' && (
        <div className="border-t border-ink-200 pt-4">
          <Field
            label={`${resourceWord(form.source_type, true)} to import automatically`}
            hint={
              connection
                ? `Choose the ${resourceWord(form.source_type, true)} this scheduled connection should refresh.`
                : undefined
            }
          >
            {connection ? (
              form.source_type === 'survey_solutions' ? (
                <QuestionnairePicker
                  connectionId={connection.id}
                  value={form.questionnaires}
                  onChange={(questionnaires) => update({ questionnaires })}
                />
              ) : (
                <ResourcePicker
                  connectionId={connection.id}
                  value={form.questionnaires}
                  onChange={(questionnaires) => update({ questionnaires })}
                  source={form.source_type}
                />
              )
            ) : (
              <p className="text-sm text-ink-500">
                Save the connection first, then reopen it to discover and choose its remote
                {` ${resourceWord(form.source_type, true)}.`}
              </p>
            )}
          </Field>
          {form.sync_enabled && !form.questionnaires.length && (
            <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Automatic imports will not run until at least one remote resource is chosen.
            </p>
          )}
        </div>
      )}

      <div className="flex flex-col items-start gap-3 border-t border-ink-200 pt-4">
        <Toggle
          checked={form.sync_enabled}
          onChange={(value) => update({ sync_enabled: value })}
          label={
            form.sync_mode === 'daily'
              ? `Import automatically at ${
                  form.sync_times.length ? form.sync_times.join(', ') : 'the times above'
                }`
              : 'Import automatically on the schedule above'
          }
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

function ResourcePicker({
  connectionId,
  value,
  onChange,
  source,
}: {
  connectionId: string
  value: string[]
  onChange: (value: string[]) => void
  source: SourceType
}) {
  const resources = useQuery({
    queryKey: ['connection-resources', connectionId],
    queryFn: () => api.get<RemoteResource[]>(`/connections/${connectionId}/resources`),
  })
  if (resources.isLoading) return <Loading />
  if (resources.error) return <ErrorNote error={resources.error} retry={resources.refetch} />
  if (!resources.data?.length) {
    return (
      <p className="rounded border border-ink-200 bg-ink-50 px-3 py-2 text-sm text-ink-500">
        No {resourceWord(source, true)} were returned by this connection.
      </p>
    )
  }
  return (
    <div className="max-h-64 space-y-1 overflow-auto rounded-card border border-ink-200 p-2">
      {resources.data.map((resource) => (
        <label
          key={resource.identity}
          className="flex cursor-pointer items-start gap-2 rounded px-2 py-2 hover:bg-ink-50"
        >
          <input
            className="mt-0.5"
            type="checkbox"
            checked={value.includes(resource.identity)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...new Set([...value, resource.identity])]
                  : value.filter((item) => item !== resource.identity),
              )
            }
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium text-ink-800">{resource.title}</span>
            <span className="block truncate font-mono text-xs text-ink-400">
              {resource.identity}
            </span>
          </span>
        </label>
      ))}
    </div>
  )
}

function ImportModal({
  connection,
  onClose,
}: {
  connection: SourceConnection
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const source = sourceOf(connection)
  const [selected, setSelected] = useState<string[]>(connection.questionnaires)
  const [projectId, setProjectId] = useState(connection.project_id ?? '')
  const [mode, setMode] = useState<'replace' | 'append'>('replace')

  const start = useMutation({
    mutationFn: () =>
      api.post(`/connections/${connection.id}/sync`, {
        questionnaires: selected,
        project_id: projectId || null,
        mode,
      }),
    onSuccess: () => {
      toast.push(
        'Import started. It runs in the background and can take a few minutes for large sources.',
        'success',
      )
      queryClient.invalidateQueries({ queryKey: ['sync-runs'] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const importLabel =
    source === 'survey_solutions'
      ? `Import ${describeSelection(selected)}`
      : `Import ${selected.length} ${resourceWord(source, selected.length !== 1)}`

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
            {importLabel}
          </button>
        </>
      }
    >
      <div className="mb-4 grid gap-x-4 sm:grid-cols-2">
        <ProjectPicker value={projectId} onChange={setProjectId} label="Import into project" />
        <Field
          label="If these datasets already exist"
          hint="Replacing keeps their dataset ids, so charts, indicators and dashboards continue to work."
        >
          <select
            className="input"
            value={mode}
            onChange={(event) => setMode(event.target.value as 'replace' | 'append')}
          >
            <option value="replace">Replace their data</option>
            <option value="append">Append these rows</option>
          </select>
        </Field>
      </div>

      <p className="mb-3 text-sm text-ink-500">
        {source === 'survey_solutions'
          ? 'Each questionnaire export becomes one dataset per roster level, including paradata.'
          : source === 'sdmx'
            ? 'Each SDMX query becomes a refreshable SurveyHQ dataset while retaining its dimensions and codes.'
            : `SurveyHQ imports each ${resourceWord(source)} and separates nested repeat/roster records into linked tabular datasets.`}
      </p>

      {source === 'survey_solutions' ? (
        <QuestionnairePicker
          connectionId={connection.id}
          value={selected}
          onChange={setSelected}
        />
      ) : source === 'sdmx' ? (
        <SdmxSelection connection={connection} value={selected} onChange={setSelected} />
      ) : (
        <ResourcePicker
          connectionId={connection.id}
          value={selected}
          onChange={setSelected}
          source={source}
        />
      )}
    </Modal>
  )
}

function SdmxSelection({
  connection,
  value,
  onChange,
}: {
  connection: SourceConnection
  value: string[]
  onChange: (value: string[]) => void
}) {
  const configured = ((connection.source_config?.resources as unknown[]) ?? [])
    .map((item) => (typeof item === 'string' ? item : String((item as any)?.path ?? '')))
    .filter(Boolean)
  const options = [...new Set([...configured, ...connection.questionnaires])]
  if (!options.length) {
    return (
      <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
        Edit this connection and add at least one SDMX data query path first.
      </p>
    )
  }
  return (
    <div className="space-y-1 rounded-card border border-ink-200 p-2">
      {options.map((path) => (
        <label key={path} className="flex cursor-pointer items-start gap-2 rounded px-2 py-2 hover:bg-ink-50">
          <input
            className="mt-0.5"
            type="checkbox"
            checked={value.includes(path)}
            onChange={(event) =>
              onChange(event.target.checked ? [...new Set([...value, path])] : value.filter((x) => x !== path))
            }
          />
          <code className="break-all text-xs text-ink-700">{path}</code>
        </label>
      ))}
    </div>
  )
}
