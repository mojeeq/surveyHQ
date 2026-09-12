import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, downloadFile } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { relativeTime } from '@/lib/format'
import type { Connection, SyncRun } from '@/lib/types'
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

type Provider =
  | 'survey_solutions'
  | 'odk_central'
  | 'kobotoolbox'
  | 'surveycto'
  | 'csweb'
  | 'sdmx'

type SourceConnection = Connection & {
  provider?: Provider
  source_config?: Record<string, unknown>
}

const PROVIDERS: Record<
  Provider,
  { label: string; description: string; urlHint: string; credential: string }
> = {
  survey_solutions: {
    label: 'Survey Solutions',
    description: 'World Bank CAPI headquarters server',
    urlHint: 'https://your-server.mysurvey.solutions',
    credential: 'user_password',
  },
  odk_central: {
    label: 'ODK Central',
    description: 'ODK forms, submissions and repeat tables',
    urlHint: 'https://central.example.org',
    credential: 'user_password',
  },
  kobotoolbox: {
    label: 'KoboToolbox',
    description: 'Kobo forms and submitted survey records',
    urlHint: 'https://kf.kobotoolbox.org',
    credential: 'token',
  },
  surveycto: {
    label: 'SurveyCTO',
    description: 'SurveyCTO forms and wide tabular exports',
    urlHint: 'https://your-server.surveycto.com',
    credential: 'user_password',
  },
  csweb: {
    label: 'CSPro / CSWeb',
    description: 'CSPro dictionaries and synchronized cases',
    urlHint: 'https://stats.example.org/csweb',
    credential: 'user_password',
  },
  sdmx: {
    label: 'SDMX REST API',
    description: 'Official-statistics data from an SDMX web service',
    urlHint: 'https://api.example.org/public/rest/v1',
    credential: 'optional',
  },
}

function providerOf(connection: SourceConnection): Provider {
  return connection.provider || 'survey_solutions'
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
  provider: 'survey_solutions' as Provider,
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
  sync_mode: 'interval' as 'interval' | 'daily',
  sync_times: [] as string[],
  sync_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  odk_project_id: '',
  sdmx_resources: '',
}

function configFromForm(form: typeof BLANK): Record<string, unknown> {
  if (form.provider === 'odk_central') {
    return form.odk_project_id.trim() ? { project_id: form.odk_project_id.trim() } : {}
  }
  if (form.provider === 'sdmx') {
    const resources = form.sdmx_resources
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [label, ...rest] = line.split('|')
        if (!rest.length) return { title: label.trim(), path: label.trim() }
        const path = rest.join('|').trim()
        return { title: label.trim() || path, path }
      })
    return { resources }
  }
  return {}
}

function sdmxText(config: Record<string, unknown> | undefined): string {
  const resources = Array.isArray(config?.resources) ? config?.resources : []
  return resources
    .map((item: any) => {
      if (typeof item === 'string') return item
      const path = String(item?.path || '')
      const title = String(item?.title || '')
      return title && title !== path ? `${title} | ${path}` : path
    })
    .filter(Boolean)
    .join('\n')
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
        description="Import survey microdata and official-statistics data directly from collection platforms and SDMX APIs."
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
            description="Connect Survey Solutions, ODK Central, KoboToolbox, SurveyCTO, CSPro/CSWeb or an SDMX REST service."
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
            const provider = providerOf(connection)
            return (
              <Card
                key={connection.id}
                title={connection.name}
                subtitle={`${PROVIDERS[provider].label} · ${connection.base_url}${
                  provider === 'survey_solutions' ? ` · workspace "${connection.workspace}"` : ''
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
                    <dt className="text-xs uppercase text-ink-400">Source</dt>
                    <dd className="text-ink-700">{PROVIDERS[provider].label}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-ink-400">Account</dt>
                    <dd className="text-ink-700">
                      {provider === 'kobotoolbox'
                        ? connection.has_password
                          ? 'API token configured'
                          : 'token not set'
                        : connection.username || (provider === 'sdmx' ? 'anonymous' : 'not set')}
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
                  title="Download the raw file exactly as the source returned it"
                  onClick={() =>
                    downloadFile(
                      `/connections/${connectionId}/runs/${run.id}/archive`,
                      undefined,
                      `${run.questionnaire || 'source-export'}`,
                      'GET',
                    )
                  }
                >
                  Download source
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
  const existingProvider = connection ? providerOf(connection) : 'survey_solutions'
  const [form, setForm] = useState({
    ...BLANK,
    ...(connection
      ? {
          provider: existingProvider,
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
          sync_mode: connection.sync_mode ?? 'interval',
          sync_times: connection.sync_times ?? [],
          sync_timezone: connection.sync_timezone || 'UTC',
          odk_project_id: String(connection.source_config?.project_id || ''),
          sdmx_resources: sdmxText(connection.source_config),
        }
      : {}),
  })
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const update = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const meta = PROVIDERS[form.provider]

  const payload = () => ({
    ...form,
    project_id: form.project_id || null,
    source_config: configFromForm(form),
  })

  const testUnsaved = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>('/connections/test', payload()),
    onSuccess: setTestResult,
    onError: (error: Error) => setTestResult({ ok: false, message: error.message }),
  })

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = payload()
      delete body.odk_project_id
      delete body.sdmx_resources
      if (connection && !form.password) delete body.password
      return connection
        ? api.patch(`/connections/${connection.id}`, body)
        : api.post('/connections', body)
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

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        {(Object.entries(PROVIDERS) as [Provider, (typeof PROVIDERS)[Provider]][]).map(
          ([provider, item]) => (
            <button
              type="button"
              key={provider}
              onClick={() => {
                update({ provider, questionnaires: [] })
                setTestResult(null)
              }}
              className={`rounded-card border p-3 text-left ${
                form.provider === provider
                  ? 'border-brand-400 bg-brand-50 ring-1 ring-brand-300'
                  : 'border-ink-200 hover:bg-ink-50'
              }`}
            >
              <p className="text-sm font-semibold text-ink-900">{item.label}</p>
              <p className="mt-1 text-xs text-ink-500">{item.description}</p>
            </button>
          ),
        )}
      </div>

      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="Connection name">
          <input
            className="input"
            value={form.name}
            onChange={(event) => update({ name: event.target.value })}
            placeholder={`${meta.label} connection`}
          />
        </Field>
        <Field label="Server / API URL" hint={meta.urlHint}>
          <input
            className="input"
            value={form.base_url}
            onChange={(event) => update({ base_url: event.target.value })}
            placeholder={meta.urlHint}
          />
        </Field>

        {form.provider === 'survey_solutions' && (
          <Field label="Workspace" hint="Usually 'primary'">
            <input
              className="input"
              value={form.workspace}
              onChange={(event) => update({ workspace: event.target.value })}
            />
          </Field>
        )}

        {form.provider === 'odk_central' && (
          <Field
            label="ODK project id"
            hint="Optional. Leave blank to discover forms from every project this account can access."
          >
            <input
              className="input"
              value={form.odk_project_id}
              onChange={(event) => update({ odk_project_id: event.target.value })}
              placeholder="1"
            />
          </Field>
        )}

        {meta.credential !== 'token' && (
          <Field
            label={form.provider === 'odk_central' ? 'ODK email / user' : 'API user name'}
            hint={form.provider === 'sdmx' ? 'Optional if the SDMX service is public' : undefined}
          >
            <input
              className="input"
              value={form.username}
              onChange={(event) => update({ username: event.target.value })}
            />
          </Field>
        )}
        <Field
          label={form.provider === 'kobotoolbox' ? 'Kobo API token' : 'Password / API secret'}
          hint={
            connection
              ? 'Leave blank to keep the stored secret'
              : form.provider === 'sdmx'
                ? 'Optional for a public SDMX endpoint'
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

        {form.provider === 'survey_solutions' && (
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

        <ProjectPicker
          value={form.project_id}
          onChange={(project_id) => update({ project_id })}
          label="Default project for imports"
          hint="Where this source's imported datasets land."
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

      {form.provider === 'sdmx' && (
        <Field
          label="SDMX data queries"
          hint="One relative data path per line. Use “Label | path” to give it a friendly name, e.g. Population | data/DF_POP/.?startPeriod=2020"
        >
          <textarea
            className="input min-h-28 font-mono text-xs"
            value={form.sdmx_resources}
            onChange={(event) => update({ sdmx_resources: event.target.value })}
            placeholder={'Population | data/DF_POP/.?startPeriod=2020\nLabour force | data/DF_LFS/..A'}
          />
        </Field>
      )}

      {form.sync_mode === 'daily' && (
        <Field
          label="Import at"
          hint="24-hour times. Imports start shortly after each configured time."
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

      <div className="border-t border-ink-200 pt-4">
        <Field
          label={
            form.provider === 'survey_solutions'
              ? 'Questionnaires to import automatically'
              : 'Resources to import automatically'
          }
          hint="Choose what a scheduled sync should refresh. A manual import can use a different selection."
        >
          {connection ? (
            <QuestionnairePicker
              connectionId={connection.id}
              provider={form.provider}
              value={form.questionnaires}
              onChange={(questionnaires) => update({ questionnaires })}
            />
          ) : (
            <p className="text-sm text-ink-500">
              Save the connection first, then reopen it to discover and choose resources from
              the source.
            </p>
          )}
        </Field>
        {form.sync_enabled && !form.questionnaires.length && (
          <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Automatic imports will not run until at least one resource is chosen here.
          </p>
        )}
      </div>

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

function ImportModal({
  connection,
  onClose,
}: {
  connection: SourceConnection
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const provider = providerOf(connection)
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
        'Import started. It runs in the background and may take a few minutes for large surveys.',
        'success',
      )
      queryClient.invalidateQueries({ queryKey: ['sync-runs'] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const selectionLabel =
    provider === 'survey_solutions'
      ? describeSelection(selected)
      : `${selected.length} resource${selected.length === 1 ? '' : 's'}`

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
            Import {selectionLabel}
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
          hint="Replacing keeps dataset ids stable, so charts, indicators and quality rules continue to work."
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

      <p className="mb-3 text-sm text-ink-500">
        SurveyHQ imports each selected source into ordinary datasets, so the same analysis,
        dashboards, indicators, monitoring and quality checks work regardless of where the data
        was collected.
      </p>
      <QuestionnairePicker
        connectionId={connection.id}
        provider={provider}
        value={selected}
        onChange={setSelected}
      />
    </Modal>
  )
}
