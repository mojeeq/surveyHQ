import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, downloadFile } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { relativeTime } from '@/lib/format'
import type { Connection, SyncRun } from '@/lib/types'
import { CONNECTION_SOURCES, externalConnectionUrl, isLinkConnection } from '@/lib/connection-sources'
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
import type { BadgeTone } from '@/components/ui'

/**
 * Every zone the browser knows, so the times are set where the fieldwork is.
 *
 * Intl.supportedValuesOf is not in every browser; where it is missing the list
 * falls back to this machine's own zone and UTC, which covers the case it
 * exists for - somebody scheduling an import for the country they are in.
 */
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
  // A server, or a folder on the SurveyHQ host that exports are put in. The
  // second is for the offices whose server administrator will not create an
  // API user: somebody puts the export where this can read it.
  source_kind: 'survey_solutions' as Connection['source_kind'],
  folder_path: '',
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
  sync_timezone:
    // The browser's own zone is nearly always the one the fieldwork is in,
    // and is a far better guess than UTC.
    Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
}

export default function Connections() {
  const { can } = useAuth()
  const toast = useToast()
  const ask = useDialog()
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
        title="Connections"
        description="Manage survey sources, spreadsheets and SharePoint folders. Survey Solutions and local folders support automatic imports."
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
            title="No connections yet"
            description="Add a survey server, spreadsheet, SharePoint folder or local import folder."
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
              subtitle={
                connection.source_kind === 'folder'
                  ? `Folder · ${connection.folder_path}`
                  : `${CONNECTION_SOURCES[connection.source_kind].label} · ${connection.base_url}`
              }
              actions={
                <>
                  {isLinkConnection(connection.source_kind) ? (
                    <>
                      <Badge tone="neutral">Saved link</Badge>
                      {externalConnectionUrl(connection.base_url) && (
                        <a className="btn-primary btn-sm" href={externalConnectionUrl(connection.base_url)}
                          target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
                          Open {CONNECTION_SOURCES[connection.source_kind].label}
                        </a>
                      )}
                    </>
                  ) : <SyncBadge connection={connection} />}
                  {!isLinkConnection(connection.source_kind) && can('manager') && (
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => test.mutate(connection.id)}
                    disabled={test.isPending}
                  >
                    Test
                  </button>
                  )}
                  {can('manager') && (
                    <>
                      {!isLinkConnection(connection.source_kind) && <button
                        className="btn-primary btn-sm"
                        onClick={() => setImporting(connection)}
                      >
                        Import data
                      </button>}
                      <button className="btn-ghost btn-sm" onClick={() => setEditing(connection)}>
                        Edit
                      </button>
                      <button
                        className="btn-ghost btn-sm text-red-600"
                        onClick={async () => {
                          const sure = await ask.confirm({
                            title: `Delete \u201C${connection.name}\u201D?`,
                            message:
                              'Datasets already pulled through it stay. Nothing further will sync.',
                            confirmLabel: 'Delete connection',
                            tone: 'danger',
                          })
                          if (sure) remove.mutate(connection.id)
                        }}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </>
              }
            >
              {isLinkConnection(connection.source_kind) ? (
                <p className="text-sm text-ink-500">
                  Opens in a new tab using your provider account. This saved link does not import or sync data.
                </p>
              ) : <dl className="grid gap-4 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-xs uppercase text-ink-500">API user</dt>
                  <dd className="text-ink-700">{connection.username || 'not set'}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-ink-500">Export format</dt>
                  <dd className="text-ink-700">{connection.export_format}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-ink-500">Scheduled sync</dt>
                  <dd className="text-ink-700">
                    {connection.sync_enabled
                      ? `every ${connection.sync_interval_minutes} min`
                      : 'off'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase text-ink-500">Last sync</dt>
                  <dd className="text-ink-700">{relativeTime(connection.last_sync_at)}</dd>
                </div>
              </dl>}
              {!isLinkConnection(connection.source_kind) && connection.last_sync_error && (
                <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {connection.last_sync_error}
                </p>
              )}
              {!isLinkConnection(connection.source_kind) && <SyncHistory connectionId={connection.id} />}
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

/**
 * The formats a Survey Solutions server will export in.
 *
 * Its API takes these three names and no others, which is why there is no
 * CSV and no .dat here: the tabular export is tab separated text, and a .tab
 * opens in Excel and reads into Stata and R like any other delimited file.
 * The extensions are on the labels because the file is what people recognise
 * - "Tabular" on its own says nothing about what lands on disk.
 */
const EXPORT_FORMATS: { value: Connection['export_format']; label: string }[] = [
  { value: 'STATA', label: 'Stata (.dta) - keeps value labels' },
  { value: 'Tabular', label: 'Tab-delimited text (.tab)' },
  { value: 'SPSS', label: 'SPSS (.sav)' },
]

function SyncBadge({ connection }: { connection: Connection }) {
  const map: Record<string, { tone: BadgeTone; icon?: string; label: string }> = {
    success: { tone: 'success', label: 'Synced' },
    failed: { tone: 'danger', icon: '⚠', label: 'Failed' },
    running: { tone: 'warning', icon: '◷', label: 'Running' },
    never: { tone: 'neutral', icon: '-', label: 'Never synced' },
  }
  const state = map[connection.last_sync_status]
  return (
    <Badge tone={state.tone} icon={state.icon}>
      {state.label}
    </Badge>
  )
}

/** The extension a format arrives as, which is what a run is recognised by. */
function formatName(value: string): string {
  const suffix: Record<string, string> = { STATA: '.dta', Tabular: '.tab', SPSS: '.sav' }
  return suffix[value] ?? value
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
      <p className="mb-2 text-xs font-semibold uppercase text-ink-500">Recent imports</p>
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
              {run.export_format && (
                <span className="text-ink-500">{formatName(run.export_format)}</span>
              )}
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
              <span className="text-ink-500">{relativeTime(run.started_at)}</span>
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
          source_kind: connection.source_kind ?? 'survey_solutions',
          folder_path: connection.folder_path ?? '',
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
        }
      : {}),
  })
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const isFolder = form.source_kind === 'folder'
  const isLink = isLinkConnection(form.source_kind)
  const source = CONNECTION_SOURCES[form.source_kind]

  const update = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })

  const testUnsaved = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>('/connections/test', { ...form, project_id: form.project_id || null }),
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
      title={connection ? 'Edit connection' : 'Add a connection'}
      wide
      footer={
        <>
          <button
            className="btn-secondary mr-auto"
            onClick={() => testUnsaved.mutate()}
            disabled={testUnsaved.isPending}
          >
            {testUnsaved.isPending && <Spinner className="h-4 w-4" />}
            {isLink ? 'Check link format' : 'Test connection'}
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
              ? 'border-ink-200 bg-ink-50 text-ink-700'
              : 'border-ink-900 bg-ink-800 text-white'
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
            data-suggest=""
          />
        </Field>
        <Field
          label="Where the data comes from"
          hint="Choose a provider or a local import folder."
        >
          <select
            className="input"
            value={form.source_kind}
            onChange={(event) =>
              update({
                source_kind: event.target.value as typeof form.source_kind,
                base_url: '', folder_path: '', username: '', password: '',
                workspace: 'primary', questionnaires: [], sync_enabled: false,
              })
            }
          >
            {Object.entries(CONNECTION_SOURCES).map(([value, entry]) => (
              <option key={value} value={value}>{entry.label}</option>
            ))}
          </select>
        </Field>

        {isFolder ? (
          <Field
            label="Folder to read"
            hint="On the SurveyHQ host, inside a folder the administrator allows. Exports put here are imported on the schedule below."
          >
            <input
              className="input"
              value={form.folder_path}
              onChange={(event) => update({ folder_path: event.target.value })}
              placeholder="/incoming"
              data-suggest=""
            />
          </Field>
        ) : (
          <>
            <Field
              label={isLink ? (form.source_kind === 'sharepoint' ? 'SharePoint folder link' : 'Source link') : 'Server URL'}
              hint={source.hint}
            >
              <input
                className="input"
                value={form.base_url}
                onChange={(event) => update({ base_url: event.target.value })}
                placeholder={source.placeholder}
              />
            </Field>
            {!isLink && <>
            <Field label="Workspace" hint="Usually 'primary'">
              <input
                className="input"
                value={form.workspace}
                onChange={(event) => update({ workspace: event.target.value })}
              />
            </Field>
            <Field
              label="API user name"
              hint="An API user or an administrator. An ordinary headquarters account cannot use the export API."
            >
              <input
                className="input"
                value={form.username}
                onChange={(event) => update({ username: event.target.value })}
              />
            </Field>
            </>}
          </>
        )}
        {!isFolder && !isLink && (
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
        )}
        {!isFolder && !isLink && (
        <Field label="Export format">
          <select
            className="input"
            value={form.export_format}
            onChange={(event) =>
              update({ export_format: event.target.value as typeof form.export_format })
            }
          >
            {EXPORT_FORMATS.map((format) => (
              <option key={format.value} value={format.value}>
                {format.label}
              </option>
            ))}
          </select>
        </Field>
        )}
        <ProjectPicker
          value={form.project_id}
          onChange={(project_id) => update({ project_id })}
          label={isLink ? 'Project' : 'Default project for imports'}
          hint={isLink ? 'Who can see this saved link is controlled by its project.' : "Where this connection's data lands. A single import can be sent elsewhere."}
        />

        {!isFolder && !isLink && (
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
        )}
        {!isLink && <>
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
        </>}
      </div>

      {isLink && (
        <p className="rounded border border-ink-200 bg-ink-50 px-3 py-2 text-sm text-ink-700">
          Saves a link for your project. Sign in on the provider’s website when you open it.
          Automatic imports are not available for this source.
          Do not paste passwords or API tokens into the link.
        </p>
      )}

      {!isLink && form.sync_mode === 'daily' && (
        <Field
          label="Import at"
          hint="24-hour times. The check runs every few minutes, so an import starts shortly after the time you set."
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

      {/* Which questionnaires the scheduled import pulls. There was nowhere to
          say, so a connection could have automatic imports switched on and a
          schedule set and still never import anything: the scheduler skips a
          connection with nothing chosen, and said nothing about it. */}
      {!isFolder && !isLink && (
      <div className="border-t border-ink-200 pt-4">
        <Field
          label="Questionnaires to import automatically"
          hint={
            connection
              ? 'Ticking a questionnaire takes every version of it, including ones published after today. A single import can still be aimed at particular versions.'
              : undefined
          }
        >
          {connection ? (
            <QuestionnairePicker
              connectionId={connection.id}
              value={form.questionnaires}
              onChange={(questionnaires) => update({ questionnaires })}
            />
          ) : (
            <p className="text-sm text-ink-500">
              Save the connection first, then reopen it to choose from the questionnaires
              on the server.
            </p>
          )}
        </Field>
        {form.sync_enabled && !form.questionnaires.length && (
          <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Automatic imports will not run until at least one questionnaire is chosen here.
          </p>
        )}
      </div>
      )}

      {/* items-start: a Toggle is an inline-flex label, so two of them in a
          space-y column sat on one line and overlapped each other's text. */}
      {!isLink && <div className="flex flex-col items-start gap-3 border-t border-ink-200 pt-4">
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
        {!isFolder && !isLink && (
          <Toggle
            checked={form.verify_ssl}
            onChange={(value) => update({ verify_ssl: value })}
            label="Verify the server's TLS certificate (recommended)"
          />
        )}
      </div>}
    </Modal>
  )
}

function ImportModal({ connection, onClose }: { connection: Connection; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  // A folder connection chooses nothing: what is in the folder is what there
  // is. Asking it which questionnaires to pull would be asking a question
  // only a server can answer, with a submit button that never enables.
  const isFolder = connection.source_kind === 'folder'
  const [selected, setSelected] = useState<string[]>(connection.questionnaires)
  const [projectId, setProjectId] = useState(connection.project_id ?? '')
  const [mode, setMode] = useState<'replace' | 'append'>('replace')
  // Starts at the connection's format and applies to this import alone, which
  // is what makes it useful: a questionnaire whose Stata file reads badly can
  // be pulled again as tabular without changing what the nightly import does.
  const [format, setFormat] = useState(connection.export_format)

  const start = useMutation({
    mutationFn: () =>
      api.post(
        `/connections/${connection.id}/sync`,
        isFolder
          ? { project_id: projectId || null, mode }
          : {
              questionnaires: selected,
              project_id: projectId || null,
              mode,
              export_format: format,
            },
      ),
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
            disabled={(!isFolder && !selected.length) || start.isPending}
          >
            {start.isPending && <Spinner className="h-4 w-4 text-white" />}
            {isFolder ? 'Import what is new' : `Import ${describeSelection(selected)}`}
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
        {!isFolder && (
        <Field
          label="Ask the server for"
          hint="This import only. The connection keeps its own default for scheduled imports."
        >
          <select
            className="input"
            value={format}
            onChange={(event) =>
              setFormat(event.target.value as Connection['export_format'])
            }
          >
            {EXPORT_FORMATS.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </select>
        </Field>
        )}
      </div>

      {isFolder ? (
        <p className="text-sm text-ink-500">
          Every file in <code>{connection.folder_path}</code> that has not been imported
          yet, and has stopped being written to, is read now - an export archive as one
          dataset per roster level, a single data file as one dataset. Re-importing
          refreshes them in place, so saved charts and indicators keep working.
        </p>
      ) : (
        <>
          <p className="mb-3 text-sm text-ink-500">
            Each questionnaire's whole export is imported - one dataset per roster level,
            with the paradata - and re-importing refreshes them in place, so saved charts
            and indicators keep working.
          </p>
          <QuestionnairePicker
            connectionId={connection.id}
            value={selected}
            onChange={setSelected}
          />
        </>
      )}
    </Modal>
  )
}
