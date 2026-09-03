import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '@/lib/api'
import { formatBytes, formatNumber, formatDate, titleCase } from '@/lib/format'
import type { Dataset, FrequencyResult, SummaryStats, Variable } from '@/lib/types'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import ChartCard from '@/components/ChartCard'
import DataTable from '@/components/DataTable'
import AssignProject from '@/components/AssignProject'
import {
  Badge,
  Card,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Spinner,
  Stat,
  Tabs,
} from '@/components/ui'

type TabId = 'variables' | 'data' | 'summary' | 'progress' | 'command'

const TYPE_TONE = {
  numeric: 'info',
  categorical: 'success',
  datetime: 'warning',
  text: 'neutral',
  boolean: 'neutral',
} as const

export default function DatasetDetail() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const [tab, setTab] = useState<TabId>('variables')
  const [search, setSearch] = useState('')
  const [inspecting, setInspecting] = useState<Variable | null>(null)
  const [labelling, setLabelling] = useState<Variable | null>(null)
  const [appending, setAppending] = useState(false)

  const toast = useToast()
  const queryClient = useQueryClient()

  const dataset = useQuery({
    queryKey: ['dataset', id],
    queryFn: () => api.get<Dataset>(`/datasets/${id}`),
  })

  const rebuild = useMutation({
    mutationFn: () => api.post<Dataset>(`/relationships/rebuild/${id}`),
    onSuccess: (rebuilt) => {
      toast.push(`Rebuilt: ${rebuilt.row_count.toLocaleString()} rows`, 'success')
      queryClient.invalidateQueries({ queryKey: ['dataset', id] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  if (dataset.isLoading) return <Loading />
  if (dataset.error) return <ErrorNote error={dataset.error} retry={dataset.refetch} />

  const data = dataset.data!
  const variables = data.variables ?? []
  const monitoringFields = data.meta?.monitoring_fields ?? {}
  const filtered = variables.filter(
    (variable) =>
      !search ||
      variable.name.toLowerCase().includes(search.toLowerCase()) ||
      variable.label.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <>
      <PageHeader
        title={data.name}
        description={data.description || `Imported ${formatDate(data.created_at)}`}
        actions={
          <>
            <AssignProject
              kind="dataset"
              id={data.id}
              projectId={data.project_id}
              canMove={can('manager')}
            />
            <Link to={`/explore?dataset=${data.id}`} className="btn-primary">
              Analyse
            </Link>
            <Link to={`/quality?dataset=${data.id}`} className="btn-secondary">
              Quality checks
            </Link>
            {can('manager') && data.derivation?.type === 'merge' && (
              // A derived dataset is defined by its recipe, so it is refreshed
              // by re-running that rather than by uploading anything.
              <button
                className="btn-secondary"
                onClick={() => rebuild.mutate()}
                disabled={rebuild.isPending}
                title="Re-run the merge against the current source datasets"
              >
                {rebuild.isPending ? 'Rebuilding…' : 'Rebuild from sources'}
              </button>
            )}
            {can('manager') && !data.derivation?.type && (
              <button className="btn-secondary" onClick={() => setAppending(true)}>
                Append data
              </button>
            )}
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Rows" value={formatNumber(data.row_count)} />
        <Stat label="Variables" value={data.column_count} />
        <Stat label="Stored size" value={formatBytes(data.file_size)} />
        <Stat
          label="Last refreshed"
          value={formatDate(data.refreshed_at ?? data.updated_at)}
          hint={`version ${data.version}`}
        />
      </div>

      {Object.keys(monitoringFields).length > 0 && (
        <Card
          className="mb-6"
          title="Recognised monitoring fields"
          subtitle="Detected automatically, used to build field-progress views with no setup"
        >
          <div className="flex flex-wrap gap-2">
            {Object.entries(monitoringFields).map(([role, column]) => (
              <span
                key={role}
                className="rounded-lg border border-ink-200 bg-ink-50 px-2.5 py-1.5 text-xs"
              >
                <span className="font-semibold text-ink-700">{titleCase(role)}</span>
                <span className="mx-1 text-ink-400">→</span>
                <code className="font-mono text-ink-600">{column}</code>
              </span>
            ))}
          </div>
        </Card>
      )}

      <Tabs<TabId>
        tabs={[
          { id: 'variables', label: 'Variables', count: variables.length },
          { id: 'data', label: 'Data' },
          { id: 'summary', label: 'Statistics' },
          { id: 'progress', label: 'Field progress' },
          ...(can('manager') ? [{ id: 'command' as const, label: 'Command' }] : []),
        ]}
        active={tab}
        onChange={setTab}
      />

      <div className="mt-4">
        {tab === 'variables' && (
          <Card
            title="Variables"
            actions={
              <input
                className="input w-56 py-1.5 text-xs"
                placeholder="Search variables…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            }
            bodyClassName="p-0"
          >
            <div className="max-h-[600px] overflow-auto">
              <table className="table-base">
                <thead className="sticky top-0">
                  <tr>
                    <th>Name</th>
                    <th>Label</th>
                    <th>Type</th>
                    <th className="text-right">Missing</th>
                    <th className="text-right">Distinct</th>
                    <th className="text-right">Range</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((variable) => (
                    <tr key={variable.id}>
                      <td className="font-mono text-xs text-ink-800">{variable.name}</td>
                      <td className="max-w-xs truncate text-ink-600">{variable.label || '–'}</td>
                      <td>
                        <Badge tone={TYPE_TONE[variable.var_type] ?? 'neutral'}>
                          {variable.var_type}
                        </Badge>
                      </td>
                      <td className="text-right tabular-nums">
                        {variable.n_missing > 0 ? (
                          <span
                            className={
                              variable.n_missing / Math.max(data.row_count, 1) > 0.2
                                ? 'font-semibold text-amber-700'
                                : ''
                            }
                          >
                            {formatNumber(variable.n_missing)}
                          </span>
                        ) : (
                          '–'
                        )}
                      </td>
                      <td className="text-right tabular-nums">{formatNumber(variable.n_unique)}</td>
                      <td className="text-right tabular-nums text-xs text-ink-500">
                        {variable.min_value !== null && variable.max_value !== null
                          ? `${formatNumber(variable.min_value, 1)} – ${formatNumber(variable.max_value, 1)}`
                          : '–'}
                      </td>
                      <td className="text-right whitespace-nowrap">
                        {can('manager') && (
                          <button
                            className="btn-ghost btn-sm"
                            onClick={() => setLabelling(variable)}
                            title="Name this variable and its codes"
                          >
                            Labels
                          </button>
                        )}
                        <button
                          className="btn-ghost btn-sm"
                          onClick={() => setInspecting(variable)}
                        >
                          Tabulate
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {tab === 'data' && <DataPreview datasetId={id} totalRows={data.row_count} />}
        {tab === 'summary' && <SummaryPanel datasetId={id} variables={variables} />}
        {tab === 'progress' && <ProgressPanel datasetId={id} />}
        {tab === 'command' && <CommandPanel datasetId={id} />}
      </div>

      {appending && <AppendModal datasetId={id} onClose={() => setAppending(false)} />}

      {inspecting && (
        <FrequencyModal
          datasetId={id}
          variable={inspecting}
          onClose={() => setInspecting(null)}
        />
      )}

      {labelling && (
        <LabelModal
          datasetId={id}
          variable={labelling}
          onClose={() => setLabelling(null)}
        />
      )}
    </>
  )
}

function DataPreview({ datasetId, totalRows }: { datasetId: string; totalRows: number }) {
  const [offset, setOffset] = useState(0)
  const limit = 50
  const preview = useQuery({
    queryKey: ['preview', datasetId, offset],
    queryFn: () =>
      api.get<{ columns: string[]; rows: unknown[][] }>(
        `/datasets/${datasetId}/preview?limit=${limit}&offset=${offset}`,
      ),
  })

  return (
    <Card
      title="Raw data"
      subtitle={`Rows ${offset + 1}–${Math.min(offset + limit, totalRows)} of ${formatNumber(totalRows)}`}
      actions={
        <div className="flex gap-1">
          <button
            className="btn-secondary btn-sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            Previous
          </button>
          <button
            className="btn-secondary btn-sm"
            disabled={offset + limit >= totalRows}
            onClick={() => setOffset(offset + limit)}
          >
            Next
          </button>
        </div>
      }
    >
      {preview.isLoading ? (
        <Loading />
      ) : preview.error ? (
        <ErrorNote error={preview.error} />
      ) : (
        <DataTable columns={preview.data!.columns} rows={preview.data!.rows} />
      )}
    </Card>
  )
}

function SummaryPanel({ datasetId, variables }: { datasetId: string; variables: Variable[] }) {
  const numeric = variables.filter((v) => v.var_type === 'numeric').map((v) => v.name)
  const summary = useQuery({
    queryKey: ['summary', datasetId],
    queryFn: () =>
      api.post<SummaryStats[]>(`/analytics/datasets/${datasetId}/summary`, numeric.slice(0, 50)),
    enabled: numeric.length > 0,
  })

  if (!numeric.length) {
    return (
      <Card>
        <p className="py-8 text-center text-sm text-ink-500">
          This dataset has no numeric variables to summarise.
        </p>
      </Card>
    )
  }
  if (summary.isLoading) return <Loading />
  if (summary.error) return <ErrorNote error={summary.error} />

  return (
    <Card title="Descriptive statistics" bodyClassName="p-0">
      <div className="overflow-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Variable</th>
              <th className="text-right">N</th>
              <th className="text-right">Missing</th>
              <th className="text-right">Mean</th>
              <th className="text-right">SD</th>
              <th className="text-right">Min</th>
              <th className="text-right">P25</th>
              <th className="text-right">Median</th>
              <th className="text-right">P75</th>
              <th className="text-right">Max</th>
            </tr>
          </thead>
          <tbody>
            {summary.data!.map((row) => (
              <tr key={row.variable}>
                <td>
                  <span className="font-mono text-xs">{row.variable}</span>
                  {row.label && <p className="text-xs text-ink-500">{row.label}</p>}
                </td>
                {[row.count, row.missing, row.mean, row.std, row.min, row.p25, row.median, row.p75, row.max].map(
                  (value, index) => (
                    <td key={index} className="text-right tabular-nums">
                      {value === null ? '–' : formatNumber(value, 2)}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function ProgressPanel({ datasetId }: { datasetId: string }) {
  const progress = useQuery({
    queryKey: ['field-progress', datasetId],
    queryFn: () =>
      api.post<any>(`/monitoring/datasets/${datasetId}/field-progress`, {
        op: 'and',
        conditions: [],
        groups: [],
      }),
  })

  if (progress.isLoading) return <Loading label="Building field progress views" />
  if (progress.error) return <ErrorNote error={progress.error} />
  const data = progress.data

  if (!data.available_views?.length) {
    return (
      <Card>
        <p className="py-8 text-center text-sm text-ink-500">
          No monitoring fields were recognised in this dataset, so field-progress views are not
          available. You can still build any chart you like in Explore.
        </p>
      </Card>
    )
  }

  const asResult = (rows: Record<string, unknown>[], dimension: string, measure: string) => ({
    columns: [
      { name: dimension, label: titleCase(dimension), type: 'dimension' as const, data_type: 'text' },
      { name: measure, label: titleCase(measure), type: 'measure' as const, data_type: 'number' },
    ],
    rows: rows.map((row) => [row[dimension], row[measure]]),
    row_count: rows.length,
    truncated: false,
    sql: '',
    duration_ms: 0,
  })

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Daily counts and the running total have very different scales, so they
          get a chart each rather than being squashed onto one axis. */}
      {data.submissions_over_time?.length > 0 && (
        <>
          <Card title="Submissions per period">
            <ChartCard
              chartType="bar"
              result={{
                columns: [
                  { name: 'period', label: 'Date', type: 'dimension', data_type: 'datetime' },
                  { name: 'count', label: 'Interviews', type: 'measure', data_type: 'number' },
                ],
                rows: data.submissions_over_time.map((row: any) => [row.period, row.count]),
                row_count: data.submissions_over_time.length,
                truncated: false,
                sql: '',
                duration_ms: 0,
              }}
            />
          </Card>
          <Card title="Cumulative submissions">
            <ChartCard
              chartType="area"
              result={{
                columns: [
                  { name: 'period', label: 'Date', type: 'dimension', data_type: 'datetime' },
                  {
                    name: 'cumulative',
                    label: 'Interviews to date',
                    type: 'measure',
                    data_type: 'number',
                  },
                ],
                rows: data.submissions_over_time.map((row: any) => [row.period, row.cumulative]),
                row_count: data.submissions_over_time.length,
                truncated: false,
                sql: '',
                duration_ms: 0,
              }}
            />
          </Card>
        </>
      )}
      {data.status_breakdown?.length > 0 && (
        <Card title="Interviews by status">
          <ChartCard
            result={asResult(data.status_breakdown, 'status', 'count')}
            chartType="donut"
          />
        </Card>
      )}
      {data.by_interviewer?.length > 0 && (
        <Card title="Interviews per interviewer">
          <ChartCard
            result={asResult(data.by_interviewer, 'interviewer', 'interviews')}
            chartType="horizontal_bar"
          />
        </Card>
      )}
      {data.coverage_by_area?.length > 0 && (
        <Card title="Coverage by area">
          <ChartCard
            result={asResult(data.coverage_by_area, 'area', 'interviews')}
            chartType="bar"
          />
        </Card>
      )}
      {data.geo_points?.length > 0 && (
        <Card title="Interview locations" subtitle={`${data.geo_points.length} points with GPS`}>
          <GeoScatter points={data.geo_points} />
        </Card>
      )}
    </div>
  )
}

function GeoScatter({ points }: { points: Record<string, unknown>[] }) {
  return (
    <ChartCard
      showToggle={false}
      chartType="scatter"
      result={{
        columns: [
          { name: 'lon', label: 'Longitude', type: 'measure', data_type: 'number' },
          { name: 'lat', label: 'Latitude', type: 'measure', data_type: 'number' },
        ],
        rows: points.map((point) => [point.lon, point.lat]),
        row_count: points.length,
        truncated: false,
        sql: '',
        duration_ms: 0,
      }}
    />
  )
}

function FrequencyModal({
  datasetId,
  variable,
  onClose,
}: {
  datasetId: string
  variable: Variable
  onClose: () => void
}) {
  const frequency = useQuery({
    queryKey: ['frequency', datasetId, variable.name],
    queryFn: () =>
      api.get<FrequencyResult>(
        `/analytics/datasets/${datasetId}/frequency/${encodeURIComponent(variable.name)}`,
      ),
  })

  return (
    <Modal open onClose={onClose} title={`Tabulation: ${variable.name}`} wide>
      {frequency.isLoading ? (
        <Loading />
      ) : frequency.error ? (
        <ErrorNote error={frequency.error} />
      ) : (
        <>
          <p className="mb-4 text-sm text-ink-500">
            {variable.label || 'No label'} · {formatNumber(frequency.data!.total)} records,{' '}
            {formatNumber(frequency.data!.missing)} missing
          </p>
          <div className="mb-5">
            <ChartCard
              showToggle={false}
              chartType={frequency.data!.rows.length > 8 ? 'horizontal_bar' : 'bar'}
              height={260}
              result={{
                columns: [
                  { name: 'label', label: variable.name, type: 'dimension', data_type: 'text' },
                  { name: 'count', label: 'Count', type: 'measure', data_type: 'number' },
                ],
                rows: frequency.data!.rows.slice(0, 25).map((row) => [row.label, row.count]),
                row_count: frequency.data!.rows.length,
                truncated: false,
                sql: '',
                duration_ms: 0,
              }}
            />
          </div>
          <div className="overflow-auto rounded-lg border border-ink-200">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Value</th>
                  <th className="text-right">Count</th>
                  <th className="text-right">%</th>
                  <th className="text-right">Valid %</th>
                  <th className="text-right">Cumulative %</th>
                </tr>
              </thead>
              <tbody>
                {frequency.data!.rows.map((row, index) => (
                  <tr key={index}>
                    <td>{row.label}</td>
                    <td className="text-right tabular-nums">{formatNumber(row.count)}</td>
                    <td className="text-right tabular-nums">{row.percent.toFixed(1)}</td>
                    <td className="text-right tabular-nums">{row.valid_percent.toFixed(1)}</td>
                    <td className="text-right tabular-nums">
                      {row.cumulative_percent.toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  )
}


function AppendModal({ datasetId, onClose }: { datasetId: string; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')

  const append = useMutation({
    mutationFn: async () => {
      const file = fileRef.current?.files?.[0]
      if (!file) throw new Error('Choose a file to append.')
      const form = new FormData()
      form.append('file', file)
      return api.upload<Dataset>(`/datasets/${datasetId}/append`, form)
    },
    onSuccess: (dataset) => {
      toast.push(`Dataset now holds ${formatNumber(dataset.row_count)} rows`, 'success')
      queryClient.invalidateQueries({ queryKey: ['dataset', datasetId] })
      queryClient.invalidateQueries({ queryKey: ['preview', datasetId] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title="Append another round"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => append.mutate()}
            disabled={append.isPending}
          >
            {append.isPending && <Spinner className="h-4 w-4 text-white" />}
            Append
          </button>
        </>
      }
    >
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}
      <p className="mb-4 text-sm text-ink-500">
        The rows are added to what is already here rather than replacing it. A{' '}
        <code className="text-xs">source_file</code> column records which file each row
        came from, so rounds can be compared. Charts and indicators built on this dataset
        keep working.
      </p>
      <Field
        label="File to append"
        hint="A data file, or a .zip of them. A variable the new file does not contain is left blank for its rows."
      >
        <input
          ref={fileRef}
          type="file"
          accept=".dta,.sav,.csv,.tab,.tsv,.txt,.xlsx,.xls,.zip"
          className="input py-1.5"
        />
      </Field>
    </Modal>
  )
}


/**
 * Naming a variable, and naming its codes.
 *
 * An export often ships neither: a column called DEM_SEX holding 1 and 2,
 * which every table then prints as "1.0" and "2.0". Nothing about the data is
 * changed here - only what the platform calls it, in every chart and table
 * that shows it. The names are kept on the dataset as well as the variable, so
 * the next export replacing the file does not take them with it.
 */
function LabelModal({
  datasetId,
  variable,
  onClose,
}: {
  datasetId: string
  variable: Variable
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [label, setLabel] = useState(variable.label ?? '')
  const [labels, setLabels] = useState<Record<string, string>>(variable.value_labels ?? {})

  // The codes actually present, so there is something to label even when the
  // file carried no labels at all - which is the case this exists for.
  const values = useQuery({
    queryKey: ['values', datasetId, variable.name],
    queryFn: () =>
      api.get<{ value: string; label: string; count: number }[]>(
        `/datasets/${datasetId}/variables/${encodeURIComponent(variable.name)}/values?limit=200`,
      ),
  })

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/datasets/${datasetId}/variables/${encodeURIComponent(variable.name)}`, {
        label,
        value_labels: labels,
      }),
    onSuccess: () => {
      toast.push('Labels saved', 'success')
      queryClient.invalidateQueries({ queryKey: ['dataset', datasetId] })
      queryClient.invalidateQueries({ queryKey: ['values', datasetId, variable.name] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  // The values endpoint orders by frequency, which is right for a chart and
  // wrong for a form: 1, 2, 3 is the order the codes are being read off in.
  const rows = [...(values.data ?? [])].sort((a, b) => {
    const [x, y] = [Number(a.value), Number(b.value)]
    if (Number.isFinite(x) && Number.isFinite(y)) return x - y
    return String(a.value).localeCompare(String(b.value))
  })
  const codes = rows.map((row) => String(row.value))
  const labellable = codes.length > 0 && codes.length <= 200

  return (
    <Modal
      open
      onClose={onClose}
      title={`Labels for ${variable.name}`}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            Save labels
          </button>
        </>
      }
    >
      <Field label="Variable label" hint="Shown instead of the column name on charts and tables.">
        <input
          className="input"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder={variable.name}
        />
      </Field>

      <Field
        label="Value labels"
        hint="What each code should read as. Leave one blank to show the code itself."
      >
        {values.isLoading ? (
          <Loading />
        ) : !labellable ? (
          <p className="text-sm text-ink-400">
            {codes.length ? 'Too many distinct values to label.' : 'This variable has no values.'}
          </p>
        ) : (
          <div className="max-h-72 space-y-1 overflow-auto pr-1">
            {rows.map((row) => {
              const code = String(row.value)
              return (
                <div key={code} className="flex items-center gap-2">
                  <span className="w-24 shrink-0 truncate font-mono text-xs text-ink-500">
                    {code}
                  </span>
                  <input
                    className="input py-1 text-sm"
                    value={labels[code] ?? ''}
                    placeholder={code}
                    onChange={(event) =>
                      setLabels({ ...labels, [code]: event.target.value })
                    }
                  />
                  <span className="w-16 shrink-0 text-right text-xs text-ink-400">
                    {row.count}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </Field>
    </Modal>
  )
}


/**
 * A Stata-style command line over the dataset.
 *
 * The idioms are the ones anybody who has prepared survey data types without
 * thinking, and reaching for a spreadsheet to add one derived column is a poor
 * substitute for them. What is typed here is not sent to the database as
 * written: it is parsed, every name in it has to be a variable of this
 * dataset, and only a listed few functions are understood.
 *
 * The commands are kept and re-run after a newer export replaces the data,
 * which is what stops a generated variable disappearing on exactly the upload
 * this platform exists to make routine.
 */
const EXAMPLES = [
  'gen adult = age >= 18',
  'gen band = 1 if age < 18',
  'replace band = 2 if age >= 18',
  'egen n_in_region = count(interview__key), by(region)',
  'egen household_size = rowtotal(men women)',
  'label variable age "Age in years"',
  'label define yn 1 "Yes" 2 "No"',
  'label values consent yn',
  'rename q1 age',
  'drop if age == .',
  'keep if region == "North"',
]

function CommandPanel({ datasetId }: { datasetId: string }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [log, setLog] = useState<{ command: string; message: string; ok: boolean }[]>([])

  const history = useQuery({
    queryKey: ['commands', datasetId],
    queryFn: () => api.get<string[]>(`/datasets/${datasetId}/commands`),
  })

  const run = useMutation({
    mutationFn: (command: string) =>
      api.post<{
        results: { command: string; message: string }[]
        error: string | null
        rows: number
        columns: number
      }>(`/datasets/${datasetId}/command`, { command }),
    onSuccess: (result) => {
      // Newest first, so a long script's last line is the one in view.
      const entries = [
        ...(result.error ? [{ command: '', message: result.error, ok: false }] : []),
        ...result.results.map((step) => ({
          command: step.command,
          message: step.message,
          ok: true,
        })),
      ].reverse()
      setLog((previous) => [...entries, ...previous])
      if (!result.error) setText('')
      queryClient.invalidateQueries({ queryKey: ['dataset', datasetId] })
      queryClient.invalidateQueries({ queryKey: ['commands', datasetId] })
      queryClient.invalidateQueries({ queryKey: ['preview', datasetId] })
    },
    onError: (error: Error, command) =>
      setLog((entries) => [{ command, message: error.message, ok: false }, ...entries]),
  })

  const forget = useMutation({
    mutationFn: () => api.delete(`/datasets/${datasetId}/commands`),
    onSuccess: () => {
      toast.push('Command history cleared', 'info')
      queryClient.invalidateQueries({ queryKey: ['commands', datasetId] })
    },
  })

  const submit = () => {
    const script = text.trim()
    if (script) run.mutate(script)
  }

  // Ctrl/Cmd+Enter runs, since Enter has to be a new line in a script box.
  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <Card title="Command">
          <textarea
            className="input min-h-[220px] font-mono text-sm"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={'* One command per line, as in a do-file\ngen adult = age >= 18\nreplace adult = 0 if age == .'}
            spellCheck={false}
            rows={10}
            autoFocus
          />
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <button className="btn-primary" onClick={submit} disabled={run.isPending || !text.trim()}>
              {run.isPending && <Spinner className="h-4 w-4 text-white" />}
              Run script
            </button>
            <span className="text-xs text-ink-400">Ctrl/⌘ + Enter</span>
            {text.trim() && (
              <button className="btn-ghost btn-sm text-ink-500" onClick={() => setText('')}>
                Clear
              </button>
            )}
          </div>
          <p className="mt-2 text-xs text-ink-500">
            Lines run top to bottom and stop at the first error; what ran before it stays
            applied, as a do-file does. <code>*</code> and <code>//</code> are comments, and{' '}
            <code>///</code> continues a line. Changes the data in place — every command is kept
            and re-run after a newer export replaces this dataset.
          </p>

          {log.length > 0 && (
            <div className="mt-4 max-h-80 overflow-auto rounded border border-ink-200 bg-ink-50 p-3 font-mono text-xs">
              {log.map((entry, index) => (
                <div key={index} className="mb-2">
                  {entry.command && <div className="text-ink-700">. {entry.command}</div>}
                  <div className={entry.ok ? 'text-green-700' : 'text-red-700'}>
                    {entry.message}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="space-y-4">
        <Card
          title="Kept for the next import"
          subtitle={`${history.data?.length ?? 0} command(s) will be re-run`}
          actions={
            (history.data?.length ?? 0) > 0 && (
              <>
                <button
                  className="btn-ghost btn-sm text-ink-500"
                  title="Put these back in the box to edit or re-run"
                  onClick={() => setText((history.data ?? []).join('\n'))}
                >
                  Edit
                </button>
                <button
                  className="btn-ghost btn-sm text-red-600"
                  onClick={() => {
                    if (confirm('Stop re-running these? What they already did stays done.'))
                      forget.mutate()
                  }}
                >
                  Clear
                </button>
              </>
            )
          }
        >
          {!history.data?.length ? (
            <p className="text-sm text-ink-400">Nothing recorded yet.</p>
          ) : (
            <ol className="space-y-1 font-mono text-xs text-ink-600">
              {history.data.map((command, index) => (
                <li key={index} className="truncate" title={command}>
                  {index + 1}. {command}
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Commands it understands">
          <ul className="space-y-1 font-mono text-xs text-ink-600">
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button
                  className="text-left hover:text-brand-700 hover:underline"
                  title="Add this line to the script"
                  onClick={() => setText((current) => (current ? `${current}\n${example}` : example))}
                >
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
