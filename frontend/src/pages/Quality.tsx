import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime, titleCase } from '@/lib/format'
import type {
  CheckType,
  Dataset,
  FilterGroup,
  Page,
  QualityRule,
  Severity,
} from '@/lib/types'
import FilterBuilder, { emptyFilter } from '@/components/FilterBuilder'
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

const CHECKS: { value: CheckType; label: string; description: string }[] = [
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
    description: 'Flags rows where one variable should relate to another but does not.',
  },
]

export default function Quality() {
  const [params, setParams] = useSearchParams()
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<QualityRule | null>(null)

  const datasets = useQuery({
    queryKey: ['datasets', 'ready'],
    queryFn: () => api.get<Page<Dataset>>('/datasets?limit=200&status=ready'),
  })
  const datasetId = params.get('dataset') ?? datasets.data?.items[0]?.id ?? ''

  const rules = useQuery({
    queryKey: ['quality-rules', datasetId],
    queryFn: () => api.get<QualityRule[]>(`/monitoring/quality-rules?dataset_id=${datasetId}`),
    enabled: Boolean(datasetId),
  })

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

  const existingNames = new Set((rules.data ?? []).map((rule) => rule.name))
  const openSuggestions = (suggestions.data ?? []).filter((s) => !existingNames.has(s.name))

  if (datasets.isLoading) return <Loading />
  if (!datasets.data?.items.length) {
    return (
      <Card>
        <EmptyState icon="✓" title="No datasets to check" description="Import data first." />
      </Card>
    )
  }

  return (
    <>
      <PageHeader
        title="Data quality"
        description="Automated checks that flag suspicious or incomplete field data."
        actions={
          <>
            <select
              className="input w-56"
              value={datasetId}
              onChange={(event) => setParams({ dataset: event.target.value })}
            >
              {datasets.data.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <button
              className="btn-secondary"
              onClick={() => runAll.mutate()}
              disabled={runAll.isPending || !rules.data?.length}
            >
              {runAll.isPending && <Spinner className="h-4 w-4" />}
              Run all
            </button>
            {can('manager') && (
              <button className="btn-primary" onClick={() => setCreating(true)}>
                Add check
              </button>
            )}
          </>
        }
      />

      {openSuggestions.length > 0 && can('manager') && (
        <Card
          className="mb-6"
          title="Recommended checks"
          subtitle="Based on what this dataset looks like"
        >
          <div className="space-y-2">
            {openSuggestions.map((suggestion, index) => (
              <div
                key={index}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-ink-200 px-3 py-2.5"
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

      {rules.isLoading ? (
        <Loading />
      ) : rules.error ? (
        <ErrorNote error={rules.error} />
      ) : !rules.data?.length ? (
        <Card>
          <EmptyState
            icon="✓"
            title="No checks configured"
            description="Add a check, or accept one of the recommendations above, to start monitoring data quality."
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {rules.data.map((rule) => {
            const result = rule.latest_result
            const failed = result && !result.passed
            return (
              <Card key={rule.id} bodyClassName="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-ink-800">{rule.name}</h3>
                      <Badge tone="neutral">{titleCase(rule.check_type)}</Badge>
                      <SeverityBadge severity={rule.severity} />
                      {result &&
                        (failed ? (
                          <Badge tone="danger" icon="⚠">
                            Failing
                          </Badge>
                        ) : (
                          <Badge tone="success" icon="✓">
                            Passing
                          </Badge>
                        ))}
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
                              {formatNumber(result.failed_rows)} of{' '}
                              {formatNumber(result.total_rows)} rows (
                              {(result.failure_rate * 100).toFixed(1)}%, threshold{' '}
                              {(rule.threshold * 100).toFixed(0)}%)
                            </span>
                          </div>
                        )}
                        <p className="mt-1 text-xs text-ink-400">
                          Last run {relativeTime(result.run_at)}
                        </p>
                      </>
                    )}
                  </div>
                  <div className="flex gap-1">
                    <button
                      className="btn-secondary btn-sm"
                      onClick={() => runOne.mutate(rule.id)}
                      disabled={runOne.isPending}
                    >
                      Run
                    </button>
                    {can('manager') && (
                      <button className="btn-secondary btn-sm" onClick={() => setEditing(rule)}>
                        Edit
                      </button>
                    )}
                    {can('manager') && (
                      <button
                        className="btn-ghost btn-sm text-red-600"
                        onClick={() => {
                          if (confirm(`Delete the check "${rule.name}"?`)) remove.mutate(rule.id)
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {creating && <CheckModal datasetId={datasetId} onClose={() => setCreating(false)} />}
      {editing && (
        <CheckModal
          key={editing.id}
          datasetId={datasetId}
          rule={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </>
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

function CheckModal({
  datasetId,
  rule,
  onClose,
}: {
  datasetId: string
  /** Editing an existing check rather than adding one. */
  rule?: QualityRule
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const editing = Boolean(rule)
  const [checkType, setCheckType] = useState<CheckType>(rule?.check_type ?? 'missing_rate')
  const [name, setName] = useState(rule?.name ?? '')
  const [severity, setSeverity] = useState<Severity>(rule?.severity ?? 'warning')
  const [threshold, setThreshold] = useState(String((rule?.threshold ?? 0) * 100))
  const [config, setConfig] = useState<Record<string, unknown>>(rule?.config ?? {})
  const [filters, setFilters] = useState<FilterGroup>(rule?.filters ?? emptyFilter())

  const dataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
  })
  const variables = dataset.data?.variables ?? []
  const numeric = variables.filter((v) => v.var_type === 'numeric')

  const create = useMutation({
    mutationFn: () => {
      const body = {
        name: name || CHECKS.find((c) => c.value === checkType)?.label,
        config,
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
            {v.label ? `${v.name} — ${v.label}` : v.name}
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
          {CHECKS.map((check) => (
            <option key={check.value} value={check.value}>
              {check.label}
            </option>
          ))}
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

      <Field
        label="Only check part of the dataset"
        hint="Both the flagged rows and the total are counted inside the filter, so the failure rate stays a rate of what was checked."
      >
        <FilterBuilder variables={variables} value={filters} onChange={setFilters} />
      </Field>
    </Modal>
  )
}
