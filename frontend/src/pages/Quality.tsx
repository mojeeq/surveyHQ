import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { measurable } from '@/lib/measures'
import { api, downloadFile } from '@/lib/api'
import ProjectFilter from '@/components/ProjectFilter'
import { useAuth } from '@/hooks/useAuth'
import { useBreadcrumbs } from '@/hooks/useBreadcrumbs'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { formatCell, formatNumber, relativeTime, titleCase } from '@/lib/format'
import type {
  CheckType,
  Dataset,
  FilterGroup,
  QualityRule,
  Severity,
} from '@/lib/types'
import FilterBuilder, { emptyFilter } from '@/components/FilterBuilder'
import { LOGIC_PRESETS } from '@/lib/logic-presets'
import LikelyDuplicatesFields from '@/components/LikelyDuplicatesFields'
import type { LikelyDuplicatesConfig } from '@/lib/likely-duplicates'
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
} from '@/components/ui'

const CHECKS: {
  value: CheckType
  label: string
  description: string
  /** Still runs, and still shown while editing one, but not offered for a new
   *  check: a Logic condition preset does the same thing without the limits. */
  retired?: boolean
}[] = [
  {
    value: 'missing_rate',
    label: 'Missing values',
    description: 'Flags a variable that is blank on too many records.',
  },
  {
    value: 'value_range',
    label: 'Value out of range',
    description: 'Flags values below a minimum or above a maximum.',
  },
  {
    value: 'duplicates',
    label: 'Duplicate records',
    description: 'Flags repeated key combinations, e.g. the same interview key twice.',
  },
  {
    value: 'likely_duplicates',
    label: 'Likely duplicates (similar records)',
    description:
      'Flags records alike enough to be one person entered twice: a name spelled differently, an age a year apart, a date of birth with the day and month swapped.',
  },
  {
    value: 'outliers',
    label: 'Statistical outliers',
    description: 'Flags values far from the rest using the IQR or z-score rule.',
  },
  {
    value: 'interview_duration',
    label: 'Interview duration',
    description: 'Flags interviews finished suspiciously fast.',
  },
  {
    value: 'gps_missing',
    label: 'Missing GPS',
    description: 'Flags records with no usable coordinates.',
  },
  {
    value: 'constant_value',
    label: 'Constant answers',
    description: 'Flags interviewers who record the same answer for everyone.',
  },
  {
    value: 'consistency',
    label: 'Cross-variable consistency',
    description:
      'Flags rows where one variable should relate to another but does not. Superseded by the Logic condition preset of the same name, which is not limited to one pair; checks already using it keep working.',
    retired: true,
  },
  {
    value: 'logic',
    label: 'Logic condition',
    description:
      'Flags rows meeting a condition you write: age under 18 and married, or an end date before its start.',
  },
]

type FailurePreview = {
  columns: string[]
  rows: unknown[][]
  total: number
  offset: number
  truncated: boolean
}

export default function Quality() {
  const [params, setParams] = useSearchParams()
  const { can } = useAuth()
  const toast = useToast()
  const ask = useDialog()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<QualityRule | null>(null)
  const [viewing, setViewing] = useState<QualityRule | null>(null)

  const datasets = useQuery({
    queryKey: ['datasets', 'ready'],
    queryFn: () => api.getAll<Dataset>('/datasets?status=ready'),
  })

  // A project narrows which datasets are on offer; a dataset narrows the
  // checks. With no dataset chosen the page is every check at once, so a
  // failing check is in sight without going through the datasets one by one.
  const project = params.get('project')
  const inProject = (datasets.data?.items ?? []).filter(
    (dataset) => project === null || (dataset.project_id ?? '') === project,
  )
  const chosen = params.get('dataset')
  const datasetId = chosen && inProject.some((d) => d.id === chosen) ? chosen : ''
  const selectedDataset = inProject.find((dataset) => dataset.id === datasetId)
  useBreadcrumbs(selectedDataset ? [{ label: selectedDataset.name }] : null)
  const choose = (next: string) => {
    const query: Record<string, string> = {}
    if (project !== null) query.project = project
    if (next) query.dataset = next
    setParams(query)
  }

  // Every check this user can see, once, read both ways: whole for the
  // all-datasets view, filtered for one dataset. One request either way, and
  // the picker can say which datasets have something failing.
  const rules = useQuery({
    queryKey: ['quality-rules', 'all'],
    queryFn: () => api.get<QualityRule[]>('/monitoring/quality-rules'),
    enabled: inProject.length > 0,
  })
  const offered = new Set(inProject.map((dataset) => dataset.id))
  const visible = (rules.data ?? []).filter((rule) => offered.has(rule.dataset_id))
  const shown = datasetId ? visible.filter((rule) => rule.dataset_id === datasetId) : visible
  const failingIn = new Map<string, number>()
  for (const rule of visible) {
    if (isFailing(rule)) failingIn.set(rule.dataset_id, (failingIn.get(rule.dataset_id) ?? 0) + 1)
  }

  const suggestions = useQuery({
    queryKey: ['quality-suggestions', datasetId],
    queryFn: () => api.get<any[]>(`/monitoring/datasets/${datasetId}/quality/suggestions`),
    enabled: Boolean(datasetId),
  })

  const runAll = useMutation({
    mutationFn: () => api.post(`/monitoring/datasets/${datasetId}/quality/run-all`),
    onSuccess: () => {
      toast.push('All checks re-run', 'success')
      queryClient.invalidateQueries({ queryKey: ['quality-rules'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const runOne = useMutation({
    mutationFn: (id: string) => api.post(`/monitoring/quality-rules/${id}/run`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['quality-rules'] }),
  })

  const accept = useMutation({
    mutationFn: (suggestion: any) =>
      api.post('/monitoring/quality-rules', {
        name: suggestion.name,
        dataset_id: datasetId,
        check_type: suggestion.check_type,
        config: suggestion.config,
        severity: suggestion.severity,
        threshold: suggestion.threshold,
      }),
    onSuccess: () => {
      toast.push('Check added', 'success')
      queryClient.invalidateQueries({ queryKey: ['quality-rules'] })
      queryClient.invalidateQueries({ queryKey: ['quality-suggestions'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/monitoring/quality-rules/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['quality-rules'] }),
  })

  const existingNames = new Set(shown.map((rule) => rule.name))
  const openSuggestions = (suggestions.data ?? []).filter((s) => !existingNames.has(s.name))

  if (datasets.isLoading) return <Loading />
  if (!datasets.data?.items.length) {
    return (
      <Card>
        <EmptyState icon="▤" title="No datasets to check" description="Import data first." />
      </Card>
    )
  }

  const card = (rule: QualityRule) => (
    <RuleCard
      key={rule.id}
      rule={rule}
      running={runOne.isPending && runOne.variables === rule.id}
      onRun={() => runOne.mutate(rule.id)}
      onView={() => setViewing(rule)}
      onEdit={() => setEditing(rule)}
      onDelete={async () => {
        const sure = await ask.confirm({
          title: `Delete “${rule.name}”?`,
          message: 'Its results go with it.',
          confirmLabel: 'Delete check',
          tone: 'danger',
        })
        if (sure) remove.mutate(rule.id)
      }}
    />
  )

  // The all-datasets view: grouped by dataset, the datasets with something
  // failing first, and within each the failing checks first.
  const groups = inProject
    .map((dataset) => ({
      dataset,
      rules: [...visible.filter((rule) => rule.dataset_id === dataset.id)].sort(byConcern),
      failing: failingIn.get(dataset.id) ?? 0,
    }))
    .filter((group) => group.rules.length > 0)
    .sort((a, b) => b.failing - a.failing || a.dataset.name.localeCompare(b.dataset.name))
  const unchecked = inProject.filter((dataset) => !visible.some((r) => r.dataset_id === dataset.id))
  const failingShown = shown.filter(isFailing).length

  return (
    <>
      <PageHeader
        title="Data quality"
        description="Automated checks that flag suspicious or incomplete field data."
        actions={
          <>
            <ProjectFilter
              value={project}
              onChange={(next) => setParams(next === null ? {} : { project: next })}
            />
            {datasetId && can('analyst') && shown.length > 0 && (
              <button
                className="btn-secondary"
                onClick={() =>
                  downloadFile(
                    `/monitoring/datasets/${datasetId}/quality/export`,
                    undefined,
                    `${selectedDataset?.name || 'dataset'}_quality.xlsx`,
                    'GET',
                  ).catch((error: Error) => toast.push(error.message, 'error'))
                }
              >
                Export quality workbook
              </button>
            )}
            {datasetId && (
              <button
                className="btn-secondary"
                onClick={() => runAll.mutate()}
                disabled={runAll.isPending || !shown.length}
              >
                {runAll.isPending && <Spinner className="h-4 w-4" />}
                Run all
              </button>
            )}
            {can('manager') && inProject.length > 0 && (
              <button className="btn-primary" onClick={() => setCreating(true)}>
                Add check
              </button>
            )}
          </>
        }
      />

      {!inProject.length ? (
        <Card>
          <EmptyState
            icon="▤"
            title="No datasets in this project"
            description="Checks are defined per dataset, so choose a project that has some."
          />
        </Card>
      ) : (
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card border border-ink-200 bg-white px-4 py-3 dark:border-dark-200 dark:bg-dark-50">
          <label
            htmlFor="quality-dataset"
            className="text-sm font-semibold text-ink-800 dark:text-dark-800"
          >
            Dataset
          </label>
          <select
            id="quality-dataset"
            className="input w-full sm:w-72"
            value={datasetId}
            onChange={(event) => choose(event.target.value)}
          >
            <option value="">All datasets</option>
            {inProject.map((item) => {
              const failing = failingIn.get(item.id) ?? 0
              return (
                <option key={item.id} value={item.id}>
                  {failing ? `${item.name} — ${failing} failing` : item.name}
                </option>
              )
            })}
          </select>
          {rules.data && (
            <span className="text-xs text-ink-600 dark:text-dark-600">
              {plural(shown.length, 'check')}
              {!datasetId && ` on ${plural(groups.length, 'dataset')}`}
              {' · '}
              {failingShown ? (
                <span className="font-medium text-red-700 dark:text-red-400">
                  {failingShown} failing
                </span>
              ) : (
                'none failing'
              )}
              {selectedDataset && (
                <>
                  {' · '}
                  <Link to={`/datasets/${selectedDataset.id}`} className="hover:underline">
                    open the dataset
                  </Link>
                </>
              )}
            </span>
          )}
        </div>
      )}

      {datasetId && openSuggestions.length > 0 && can('manager') && (
        <Card
          className="mb-6"
          title="Recommended checks"
          subtitle="Based on what this dataset looks like"
        >
          <div className="space-y-2">
            {openSuggestions.map((suggestion, index) => (
              <div
                key={index}
                className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-ink-200 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink-800">{suggestion.name}</p>
                  <p className="text-xs text-ink-500">{suggestion.rationale}</p>
                </div>
                <button
                  className="btn-secondary btn-sm"
                  onClick={() => accept.mutate(suggestion)}
                  disabled={accept.isPending}
                >
                  Add this check
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {!inProject.length ? null : rules.isLoading ? (
        <Loading />
      ) : rules.error ? (
        <ErrorNote error={rules.error} />
      ) : datasetId ? (
        !shown.length ? (
          <Card>
            <EmptyState
              icon="◎"
              title="No checks configured"
              description="Add a check, or accept one of the recommendations above, to start monitoring data quality."
            />
          </Card>
        ) : (
          <div className="space-y-3">{shown.map((rule) => card(rule))}</div>
        )
      ) : (
        <div className="space-y-6">
          {!groups.length && (
            <Card>
              <EmptyState
                icon="◎"
                title="No checks yet"
                description="Choose a dataset above to see the checks recommended for it, or add one."
              />
            </Card>
          )}
          {groups.map((group) => (
            <section key={group.dataset.id} aria-labelledby={`quality-${group.dataset.id}`}>
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <h2
                  id={`quality-${group.dataset.id}`}
                  className="text-sm font-semibold text-ink-800 dark:text-dark-800"
                >
                  {group.dataset.name}
                  <span className="ml-2 text-xs font-normal text-ink-600 dark:text-dark-600">
                    {plural(group.rules.length, 'check')}
                    {group.failing > 0 && `, ${group.failing} failing`}
                  </span>
                </h2>
                <button
                  className="btn-ghost btn-sm"
                  onClick={() => choose(group.dataset.id)}
                >
                  Only this dataset
                </button>
              </div>
              <div className="space-y-3">{group.rules.map((rule) => card(rule))}</div>
            </section>
          ))}
          {unchecked.length > 0 && (
            <Card title="No checks yet" subtitle="Open one to see the checks recommended for it">
              <div className="flex flex-wrap gap-2">
                {unchecked.map((dataset) => (
                  <button
                    key={dataset.id}
                    className="btn-secondary btn-sm"
                    onClick={() => choose(dataset.id)}
                  >
                    {dataset.name}
                  </button>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {viewing && <FailuresModal rule={viewing} onClose={() => setViewing(null)} />}
      {creating && (
        <CheckModal
          datasetId={datasetId}
          datasets={datasetId ? undefined : inProject}
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <CheckModal
          key={editing.id}
          datasetId={editing.dataset_id}
          rule={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  )
}

function plural(count: number, word: string): string {
  return `${formatNumber(count)} ${word}${count === 1 ? '' : 's'}`
}

function isFailing(rule: QualityRule): boolean {
  return Boolean(rule.latest_result && !rule.latest_result.passed)
}

const SEVERITY_ORDER: Record<Severity, number> = { critical: 0, warning: 1, info: 2 }

/** Failing first, then not run yet, then passing; the most severe first in each. */
function byConcern(a: QualityRule, b: QualityRule): number {
  const state = (rule: QualityRule) =>
    !rule.latest_result ? 1 : rule.latest_result.passed ? 2 : 0
  return (
    state(a) - state(b) ||
    SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
    a.name.localeCompare(b.name)
  )
}

function RuleCard({
  rule,
  running,
  onRun,
  onView,
  onEdit,
  onDelete,
}: {
  rule: QualityRule
  running: boolean
  onRun: () => void
  onView: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const { can } = useAuth()
  const toast = useToast()
  const result = rule.latest_result
  const failed = result && !result.passed
  return (
    <Card bodyClassName="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-ink-800">{rule.name}</h3>
            <Badge tone="neutral">{titleCase(rule.check_type)}</Badge>
            <SeverityBadge severity={rule.severity} />
            {result ? (
              failed ? (
                <Badge tone="danger" icon="⚠">
                  Failing
                </Badge>
              ) : (
                <Badge tone="success">Passing</Badge>
              )
            ) : (
              <Badge tone="neutral">Not run yet</Badge>
            )}
          </div>
          {result && (
            <>
              <p className="mt-1.5 text-sm text-ink-600">{result.message}</p>
              {result.total_rows > 0 && (
                <div className="mt-2 flex items-center gap-3">
                  <div className="h-1.5 w-40 overflow-hidden rounded-full bg-ink-100">
                    <div
                      className={`h-full rounded-full ${failed ? 'bg-red-500' : 'bg-emerald-500'}`}
                      style={{
                        width: `${Math.min(result.failure_rate * 100, 100).toFixed(1)}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs text-ink-500">
                    {formatNumber(result.failed_rows)} of {formatNumber(result.total_rows)} rows (
                    {(result.failure_rate * 100).toFixed(1)}%, threshold{' '}
                    {(rule.threshold * 100).toFixed(0)}%)
                  </span>
                </div>
              )}
              <p className="mt-1 text-xs text-ink-500">Last run {relativeTime(result.run_at)}</p>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-1">
          {can('analyst') && Boolean(result?.failed_rows) && (
            <button className="btn-secondary btn-sm" onClick={onView}>
              View failed records
            </button>
          )}
          {can('analyst') && Boolean(result?.failed_rows) && (
            <button
              className="btn-secondary btn-sm"
              onClick={() =>
                downloadFile(
                  `/monitoring/quality-rules/${rule.id}/failures/export?format=xlsx`,
                  undefined,
                  `${rule.name}_failures.xlsx`,
                  'GET',
                ).catch((error: Error) => toast.push(error.message, 'error'))
              }
            >
              Excel
            </button>
          )}
          <button className="btn-secondary btn-sm" onClick={onRun} disabled={running}>
            {running && <Spinner className="h-3.5 w-3.5" />}
            Run
          </button>
          {can('manager') && (
            <button className="btn-secondary btn-sm" onClick={onEdit}>
              Edit
            </button>
          )}
          {can('manager') && (
            <button className="btn-ghost btn-sm text-red-600" onClick={onDelete}>
              Delete
            </button>
          )}
        </div>
      </div>
    </Card>
  )
}

function SeverityBadge({ severity }: { severity: Severity }) {
  const map = {
    info: { tone: 'info', icon: 'ℹ' },
    warning: { tone: 'warning', icon: '▲' },
    critical: { tone: 'danger', icon: '■' },
  } as const
  return (
    <Badge tone={map[severity].tone} icon={map[severity].icon}>
      {severity}
    </Badge>
  )
}

function FailuresModal({ rule, onClose }: { rule: QualityRule; onClose: () => void }) {
  const toast = useToast()
  const failures = useQuery({
    queryKey: ['quality-failures', rule.id],
    queryFn: () =>
      api.get<FailurePreview>(`/monitoring/quality-rules/${rule.id}/failures?limit=200`),
  })

  return (
    <Modal
      open
      wide
      onClose={onClose}
      title={`Failed records: ${rule.name}`}
      footer={
        <>
          <button
            className="btn-secondary"
            onClick={() =>
              downloadFile(
                `/monitoring/quality-rules/${rule.id}/failures/export?format=csv`,
                undefined,
                `${rule.name}_failures.csv`,
                'GET',
              ).catch((error: Error) => toast.push(error.message, 'error'))
            }
          >
            CSV
          </button>
          <button
            className="btn-secondary"
            onClick={() =>
              downloadFile(
                `/monitoring/quality-rules/${rule.id}/failures/export?format=xlsx`,
                undefined,
                `${rule.name}_failures.xlsx`,
                'GET',
              ).catch((error: Error) => toast.push(error.message, 'error'))
            }
          >
            Excel
          </button>
          <button className="btn-primary" onClick={onClose}>
            Close
          </button>
        </>
      }
    >
      {failures.isLoading ? (
        <Loading label="Finding failed records" />
      ) : failures.error ? (
        <ErrorNote error={failures.error} />
      ) : !failures.data?.rows.length ? (
        <EmptyState icon="▤" title="No failed records" description="This rule currently finds no matching rows." />
      ) : (
        <>
          <p className="mb-3 text-sm text-ink-500">
            Showing {formatNumber(failures.data.rows.length)} of{' '}
            {formatNumber(failures.data.total)} matching records.
            {rule.check_type === 'duplicates' &&
              ' Duplicate checks show every row in each duplicate group so the copies can be compared.'}
            {rule.check_type === 'likely_duplicates' &&
              ' Shown in pairs, the most alike first: the two rows with the same pair number are the two records that look like one. A record alike to several others appears once in each of its pairs.'}
          </p>
          <div className="max-h-[60vh] overflow-auto rounded-card border border-ink-200">
            <table className="table-base">
              <thead className="sticky top-0">
                <tr>
                  {failures.data.columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {failures.data.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((value, cellIndex) => (
                      <td key={cellIndex}>{formatCell(value)}</td>
                    ))}
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

function CheckModal({
  datasetId: given,
  datasets,
  rule,
  onClose,
}: {
  datasetId: string
  /** Opened from the all-datasets view: which dataset is asked first. */
  datasets?: Dataset[]
  /** Editing an existing check rather than adding one. */
  rule?: QualityRule
  onClose: () => void
}) {
  const [datasetId, setDatasetId] = useState(given || datasets?.[0]?.id || '')
  const toast = useToast()
  const ask = useDialog()
  const queryClient = useQueryClient()
  const editing = Boolean(rule)
  const [checkType, setCheckType] = useState<CheckType>(rule?.check_type ?? 'missing_rate')
  const [name, setName] = useState(rule?.name ?? '')
  const [severity, setSeverity] = useState<Severity>(rule?.severity ?? 'warning')
  const [threshold, setThreshold] = useState(String((rule?.threshold ?? 0) * 100))
  const [config, setConfig] = useState<Record<string, unknown>>(rule?.config ?? {})
  const [filters, setFilters] = useState<FilterGroup>(rule?.filters ?? emptyFilter())
  // Open where this check is already restricted, asked for by name otherwise.
  const [scoped, setScoped] = useState(
    Boolean(rule?.filters?.conditions?.length || rule?.filters?.groups?.length),
  )
  // A logic rule's condition rides in `config`, which is an untyped bag shared
  // by every check type. Held as its own state so the builder has a FilterGroup
  // to work on, and folded back in on save.
  const [condition, setCondition] = useState<FilterGroup>(
    (rule?.config?.condition as FilterGroup | undefined) ?? emptyFilter(),
  )

  const dataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
  })
  const variables = dataset.data?.variables ?? []
  // A range check needs a number, not a variable somebody called a
  // quantity: see lib/measures.
  const numeric = measurable(variables)

  const create = useMutation({
    mutationFn: () => {
      const body = {
        name: name || CHECKS.find((c) => c.value === checkType)?.label,
        config: checkType === 'logic' ? { ...config, condition } : config,
        severity,
        threshold: Number(threshold) / 100,
        filters,
      }
      // check_type and dataset_id define what the check *is*; changing either
      // would make it a different check, so an edit leaves them alone.
      return rule
        ? api.patch(`/monitoring/quality-rules/${rule.id}`, body)
        : api.post('/monitoring/quality-rules', {
            ...body,
            dataset_id: datasetId,
            check_type: checkType,
          })
    },
    onSuccess: () => {
      toast.push(editing ? 'Check updated and re-run' : 'Check created and run', 'success')
      queryClient.invalidateQueries({ queryKey: ['quality-rules'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const definition = CHECKS.find((c) => c.value === checkType)!
  const set = (patch: Record<string, unknown>) => setConfig({ ...config, ...patch })

  const variableSelect = (key: string, label: string, list = variables) => (
    <Field label={label}>
      <select
        className="input"
        value={String(config[key] ?? '')}
        onChange={(event) => set({ [key]: event.target.value })}
      >
        <option value="">Choose a variable…</option>
        {list.map((v) => (
          <option key={v.name} value={v.name}>
            {v.label ? `${v.name} - ${v.label}` : v.name}
          </option>
        ))}
      </select>
    </Field>
  )

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? `Edit "${rule!.name}"` : 'Add a data quality check'}
      wide
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending && <Spinner className="h-4 w-4 text-white" />}
            {editing ? 'Save and re-run' : 'Create and run'}
          </button>
        </>
      }
    >
      {datasets && !editing && (
        <Field label="Dataset" hint="Which dataset this check looks at">
          <select
            className="input"
            value={datasetId}
            onChange={(event) => {
              setDatasetId(event.target.value)
              // Variables chosen belong to the dataset they were chosen from.
              setConfig({})
              setFilters(emptyFilter())
              setCondition(emptyFilter())
            }}
          >
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      <Field label="Check type" hint={definition.description}>
        <select
          className="input"
          disabled={editing}
          value={checkType}
          onChange={(event) => {
            setCheckType(event.target.value as CheckType)
            setConfig({})
          }}
        >
          {CHECKS.filter((check) => !check.retired || check.value === checkType).map(
            (check) => (
              <option key={check.value} value={check.value}>
                {check.label}
              </option>
            ),
          )}
        </select>
      </Field>

      {['missing_rate', 'outliers', 'constant_value'].includes(checkType) &&
        variableSelect('variable', 'Variable')}

      {checkType === 'value_range' && (
        <>
          {variableSelect('variable', 'Variable', numeric)}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Minimum allowed">
              <input
                className="input"
                type="number"
                onChange={(event) =>
                  set({ min: event.target.value === '' ? null : Number(event.target.value) })
                }
              />
            </Field>
            <Field label="Maximum allowed">
              <input
                className="input"
                type="number"
                onChange={(event) =>
                  set({ max: event.target.value === '' ? null : Number(event.target.value) })
                }
              />
            </Field>
          </div>
        </>
      )}

      {checkType === 'duplicates' && (
        <Field label="Key variables" hint="Rows sharing all of these values count as duplicates">
          <select
            className="input h-32"
            multiple
            onChange={(event) =>
              set({
                variables: Array.from(event.target.selectedOptions).map((option) => option.value),
              })
            }
          >
            {variables.map((v) => (
              <option key={v.name} value={v.name}>
                {v.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      {checkType === 'likely_duplicates' && (
        <LikelyDuplicatesFields
          variables={variables}
          config={config as LikelyDuplicatesConfig}
          onChange={(next) => setConfig(next as Record<string, unknown>)}
        />
      )}

      {checkType === 'interview_duration' && (
        <>
          {variableSelect('variable', 'Duration variable (minutes)', numeric)}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Minimum minutes">
              <input
                className="input"
                type="number"
                defaultValue={10}
                onChange={(event) => set({ min_minutes: Number(event.target.value) })}
              />
            </Field>
            <Field label="Maximum minutes (optional)">
              <input
                className="input"
                type="number"
                onChange={(event) =>
                  set({
                    max_minutes: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
              />
            </Field>
          </div>
        </>
      )}

      {checkType === 'gps_missing' && (
        <>
          {variableSelect('latitude_variable', 'Latitude variable', numeric)}
          {variableSelect('longitude_variable', 'Longitude variable', numeric)}
        </>
      )}

      {checkType === 'constant_value' && (
        <>
          {variableSelect('group_variable', 'Group by (e.g. interviewer)')}
          <Field label="Minimum interviews per group">
            <input
              className="input"
              type="number"
              defaultValue={5}
              onChange={(event) => set({ min_records: Number(event.target.value) })}
            />
          </Field>
        </>
      )}

      {checkType === 'consistency' && (
        <>
          {variableSelect('variable', 'First variable', numeric)}
          <Field label="Expected relationship">
            <select className="input" onChange={(event) => set({ operator: event.target.value })}>
              <option value="lte">must be at most</option>
              <option value="lt">must be less than</option>
              <option value="gte">must be at least</option>
              <option value="gt">must be greater than</option>
              <option value="eq">must equal</option>
            </select>
          </Field>
          {variableSelect('other_variable', 'Second variable', numeric)}
        </>
      )}

      {/*
        One question, asked once: which rows are wrong, and what makes them
        wrong. It read as three - a direction, a preset and a condition, each
        with its own label and its own paragraph - which is three headings
        over one thought and twice as much prose as the thought needs. The
        guide carries the long version.
      */}
      {checkType === 'logic' && (
        <Field
          label="Which rows are the problem"
          hint="A row is left unjudged, not flagged, when a value the condition needs is missing - use a Missing values check for those."
        >
          <select
            className="input"
            value={String(config.flag ?? 'match')}
            onChange={(event) => set({ flag: event.target.value })}
          >
            <option value="match">The rows that match the condition below</option>
            <option value="no_match">The rows that do NOT match it</option>
          </select>

          {/* A starting point is an aside, not a step of its own: one line
              above the builder it fills, rather than a labelled field with a
              paragraph under it. */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-500 dark:text-dark-500">Start from</span>
            {LOGIC_PRESETS.map((preset) => (
              <button
                key={preset.id}
                className="btn-ghost btn-sm"
                title={preset.hint}
                onClick={async () => {
                  const clear =
                    !condition.conditions.length
                    || (await ask.confirm({
                      title: 'Replace the condition you have built?',
                      message: 'The preset starts again from its own rows.',
                      confirmLabel: 'Replace',
                      tone: 'danger',
                    }))
                  if (clear) {
                    setCondition(preset.build(variables))
                    set({ flag: preset.flag })
                  }
                }}
              >
                {preset.label}
              </button>
            ))}
          </div>

          <div className="mt-2.5">
            <FilterBuilder
              variables={variables}
              value={condition}
              onChange={setCondition}
              allowVariableComparison
            />
          </div>
        </Field>
      )}

      <div className="grid grid-cols-2 gap-4">
        <Field label="Severity">
          <select
            className="input"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as Severity)}
          >
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </Field>
        <Field
          label="Tolerance (%)"
          hint="The check fails when more than this share of rows is flagged"
        >
          <input
            className="input"
            type="number"
            min={0}
            max={100}
            value={threshold}
            onChange={(event) => setThreshold(event.target.value)}
          />
        </Field>
      </div>

      <Field label="Name" hint="Defaults to the check type">
        <input className="input" value={name} onChange={(event) => setName(event.target.value)} />
      </Field>

      {/*
        Most checks run over the whole dataset, and an empty builder here is a
        second "+ Add filter / + Add group" directly under the condition's
        own - the same control twice, for something the check usually does
        not do. Asked for by name instead, and open from the start where the
        check already has one.
      */}
      {scoped ? (
        <Field
          label="Only check part of the dataset"
          hint="Both the flagged rows and the total are counted inside the filter, so the failure rate stays a rate of what was checked."
        >
          <FilterBuilder variables={variables} value={filters} onChange={setFilters} />
        </Field>
      ) : (
        <button className="btn-secondary btn-sm" onClick={() => setScoped(true)}>
          + Only check part of the dataset
        </button>
      )}
    </Modal>
  )
}
