import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { buildSparkline, STATUS_COLORS } from '@/lib/charts'
import { formatNumber, formatValue, relativeTime } from '@/lib/format'
import type {
  Aggregation,
  Dataset,
  Direction,
  FilterGroup,
  Indicator,
  IndicatorValue,
  Page,
} from '@/lib/types'
import ChartCard from '@/components/ChartCard'
import ProjectFilter, { projectParam } from '@/components/ProjectFilter'
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

const STATE = {
  ok: { tone: 'success', icon: '✓', label: 'On track' },
  warning: { tone: 'warning', icon: '▲', label: 'Watch' },
  critical: { tone: 'danger', icon: '■', label: 'Critical' },
  unknown: { tone: 'neutral', icon: '–', label: 'No data' },
} as const

export default function Monitoring() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [project, setProject] = useState<string | null>(null)

  const values = useQuery({
    queryKey: ['indicator-values', 'monitoring', project],
    queryFn: () =>
      api.get<IndicatorValue[]>(
        `/monitoring/indicators/values?trend_points=60${projectParam(project)}`,
      ),
    refetchInterval: 120_000,
  })
  const indicators = useQuery({
    queryKey: ['indicators', project],
    queryFn: () =>
      api.get<Indicator[]>(`/monitoring/indicators?${projectParam(project).slice(1)}`),
  })

  const refreshAll = useMutation({
    mutationFn: () => api.get<IndicatorValue[]>('/monitoring/indicators/values?refresh=true'),
    onSuccess: () => {
      toast.push('Indicators recalculated', 'success')
      queryClient.invalidateQueries({ queryKey: ['indicator-values'] })
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/monitoring/indicators/${id}`),
    onSuccess: () => {
      toast.push('Indicator deleted', 'success')
      queryClient.invalidateQueries({ queryKey: ['indicator-values'] })
      queryClient.invalidateQueries({ queryKey: ['indicators'] })
    },
  })

  return (
    <>
      <PageHeader
        title="Monitoring"
        description="Track the numbers that tell you whether field work is on course."
        actions={
          <>
            <button
              className="btn-secondary"
              onClick={() => refreshAll.mutate()}
              disabled={refreshAll.isPending}
            >
              {refreshAll.isPending && <Spinner className="h-4 w-4" />}
              Recalculate
            </button>
            {can('manager') && (
              <button className="btn-primary" onClick={() => setCreating(true)}>
                New indicator
              </button>
            )}
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <ProjectFilter value={project} onChange={setProject} />
        {project !== null && (
          <span className="text-xs text-ink-400">
            Indicators follow the project their dataset belongs to.
          </span>
        )}
      </div>

      {values.isLoading ? (
        <Loading />
      ) : values.error ? (
        <ErrorNote error={values.error} retry={values.refetch} />
      ) : !values.data?.length ? (
        <Card>
          <EmptyState
            icon="◎"
            title={project === null ? 'No indicators yet' : 'No indicators in this project'}
            description="An indicator is a single tracked number, such as completed interviews or mean household size, with an optional target and warning thresholds."
            action={
              can('manager') && (
                <button className="btn-primary btn-sm" onClick={() => setCreating(true)}>
                  Create your first indicator
                </button>
              )
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {values.data.map((value) => {
            const definition = indicators.data?.find((i) => i.id === value.indicator_id)
            return (
              <IndicatorCard
                key={value.indicator_id}
                value={value}
                definition={definition}
                canManage={can('manager')}
                onDelete={() => {
                  if (confirm(`Delete the indicator "${value.name}"?`))
                    remove.mutate(value.indicator_id)
                }}
              />
            )
          })}
        </div>
      )}

      {creating && <IndicatorModal onClose={() => setCreating(false)} />}
    </>
  )
}

function IndicatorCard({
  value,
  definition,
  canManage,
  onDelete,
}: {
  value: IndicatorValue
  definition?: Indicator
  canManage: boolean
  onDelete: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const state = STATE[value.status] ?? STATE.unknown
  const color = STATUS_COLORS[value.status] ?? STATUS_COLORS.unknown

  const breakdown = useQuery({
    queryKey: ['indicator-breakdown', value.indicator_id],
    queryFn: () => api.post<IndicatorValue>(`/monitoring/indicators/${value.indicator_id}/refresh`),
    enabled: expanded && Boolean(definition?.breakdown_variable),
  })

  return (
    <Card
      title={value.name}
      subtitle={definition?.description}
      actions={
        <>
          <Badge tone={state.tone} icon={state.icon}>
            {state.label}
          </Badge>
          {canManage && (
            <button className="btn-ghost btn-sm text-red-600" onClick={onDelete}>
              ✕
            </button>
          )}
        </>
      }
    >
      {value.error && (
        <p className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {value.error}
        </p>
      )}

      <p className="text-3xl font-semibold tabular-nums text-ink-900">
        {formatValue(value.value, value.value_format, value.unit)}
      </p>

      {value.target_value !== null && (
        <>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-ink-100">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(value.progress_percent ?? 0, 100)}%`,
                backgroundColor: color,
              }}
            />
          </div>
          <p className="mt-1.5 text-xs text-ink-500">
            {value.progress_percent?.toFixed(0) ?? '–'}% of target{' '}
            {formatNumber(value.target_value)}
          </p>
        </>
      )}

      {value.trend.length > 2 && (
        <div className="mt-3">
          <p className="mb-1 text-[11px] uppercase tracking-wide text-ink-400">
            Trend ({value.trend.length} points)
          </p>
          <ReactECharts option={buildSparkline(value.trend)} style={{ height: 60 }} notMerge />
        </div>
      )}

      <div className="mt-3 flex items-center justify-between border-t border-ink-100 pt-2 text-xs text-ink-400">
        <span>Updated {relativeTime(value.computed_at)}</span>
        {definition?.breakdown_variable && (
          <button className="text-brand-600 hover:underline" onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Hide' : 'Show'} by {definition.breakdown_variable}
          </button>
        )}
      </div>

      {expanded && breakdown.data && Object.keys(breakdown.data.breakdown).length > 0 && (
        <div className="mt-3">
          <ChartCard
            showToggle={false}
            chartType="horizontal_bar"
            height={200}
            result={{
              columns: [
                {
                  name: 'group',
                  label: definition?.breakdown_variable ?? 'Group',
                  type: 'dimension',
                  data_type: 'text',
                },
                { name: 'value', label: value.name, type: 'measure', data_type: 'number' },
              ],
              rows: Object.entries(breakdown.data.breakdown).map(([key, val]) => [key, val]),
              row_count: Object.keys(breakdown.data.breakdown).length,
              truncated: false,
              sql: '',
              duration_ms: 0,
            }}
          />
        </div>
      )}
    </Card>
  )
}

/**
 * What an indicator counts, in the words the answer is usually asked in.
 *
 * The creator used to offer only aggregations of a numeric variable, which
 * quietly ruled out most of a questionnaire: a status, a yes/no, a chosen
 * option are all categorical, and the number wanted from them is how many rows
 * are in a given category - or, far more often, what share of the rows are.
 */
const MEASURES: {
  value: MeasureKind
  label: string
  agg: Aggregation
  needsVariable: boolean
  numericOnly: boolean
}[] = [
  { value: 'records', label: 'Records', agg: 'count', needsVariable: false, numericOnly: false },
  {
    value: 'answered',
    label: 'Records that answered a question',
    agg: 'count',
    needsVariable: true,
    numericOnly: false,
  },
  { value: 'sum', label: 'Sum of', agg: 'sum', needsVariable: true, numericOnly: true },
  { value: 'mean', label: 'Mean of', agg: 'mean', needsVariable: true, numericOnly: true },
  { value: 'median', label: 'Median of', agg: 'median', needsVariable: true, numericOnly: true },
  {
    value: 'distinct',
    label: 'Different values of',
    agg: 'count_distinct',
    needsVariable: true,
    numericOnly: false,
  },
]

type MeasureKind = 'records' | 'answered' | 'sum' | 'mean' | 'median' | 'distinct'
type PercentOf = '' | 'all_rows' | 'answered'

function IndicatorModal({ onClose }: { onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [datasetId, setDatasetId] = useState('')
  const [name, setName] = useState('')
  const [kind, setKind] = useState<MeasureKind>('records')
  const [variable, setVariable] = useState('')
  const [where, setWhere] = useState<FilterGroup>(emptyFilter())
  const [percentOf, setPercentOf] = useState<PercentOf>('')
  const [breakdown, setBreakdown] = useState('')
  const [target, setTarget] = useState('')
  const [warning, setWarning] = useState('')
  const [critical, setCritical] = useState('')
  const [direction, setDirection] = useState<Direction>('higher_is_better')

  const datasets = useQuery({
    queryKey: ['datasets', 'ready'],
    queryFn: () => api.get<Page<Dataset>>('/datasets?limit=200&status=ready'),
  })
  const dataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: Boolean(datasetId),
  })

  const variables = dataset.data?.variables ?? []
  const numeric = variables.filter((v) => v.var_type === 'numeric')
  const groupable = variables.filter((v) => v.var_type === 'categorical' || v.n_unique <= 100)
  const measure = MEASURES.find((m) => m.value === kind)!
  const choices = measure.numericOnly ? numeric : variables
  const isPercent = percentOf !== ''

  // Only a counted measure has a meaningful share: the mean of a variable is
  // not a portion of anything, and dividing it by a row count says nothing.
  const canBePercent = kind === 'records' || kind === 'answered'

  const create = useMutation({
    mutationFn: () =>
      api.post('/monitoring/indicators', {
        name,
        dataset_id: datasetId,
        spec: {
          dimensions: [],
          measures: [
            {
              agg: measure.agg,
              variable: measure.needsVariable ? variable : null,
              alias: 'value',
            },
          ],
          filters: where,
          sort: [],
          limit: 1,
        },
        breakdown_variable: breakdown,
        percent_of: canBePercent ? percentOf : '',
        // A percentage says so in how it is written, rather than in a unit
        // typed by hand that the tile would then print twice.
        value_format: isPercent && canBePercent ? 'percent' : 'number',
        target_value: target ? Number(target) : null,
        warning_threshold: warning ? Number(warning) : null,
        critical_threshold: critical ? Number(critical) : null,
        direction,
      }),
    onSuccess: () => {
      toast.push('Indicator created', 'success')
      queryClient.invalidateQueries({ queryKey: ['indicator-values'] })
      queryClient.invalidateQueries({ queryKey: ['indicators'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const ready = name && datasetId && (!measure.needsVariable || variable)

  return (
    <Modal
      open
      onClose={onClose}
      title="New indicator"
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
            {create.isPending && <Spinner className="h-4 w-4 text-white" />}
            Create indicator
          </button>
        </>
      }
    >
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="Indicator name">
          <input
            className="input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Completion rate"
          />
        </Field>
        <Field label="Dataset">
          <select
            className="input"
            value={datasetId}
            onChange={(event) => {
              setDatasetId(event.target.value)
              setVariable('')
              setBreakdown('')
              setWhere(emptyFilter())
            }}
          >
            <option value="">Choose a dataset…</option>
            {datasets.data?.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Count">
          <select
            className="input"
            value={kind}
            onChange={(event) => {
              const next = event.target.value as MeasureKind
              setKind(next)
              setVariable('')
              if (next !== 'records' && next !== 'answered') setPercentOf('')
            }}
          >
            {MEASURES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        {measure.needsVariable && (
          <Field label={measure.numericOnly ? 'Numeric variable' : 'Variable'}>
            <select
              className="input"
              value={variable}
              onChange={(event) => setVariable(event.target.value)}
            >
              <option value="">Choose a variable…</option>
              {choices.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.label ? `${v.name} — ${v.label}` : v.name}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>

      <Field
        label="Only the records where"
        hint="Optional. This is where a status, a yes/no or a chosen option goes - the values are offered by name."
      >
        {datasetId ? (
          <FilterBuilder variables={variables} value={where} onChange={setWhere} />
        ) : (
          <p className="text-xs text-ink-400">Choose a dataset first.</p>
        )}
      </Field>

      {canBePercent && (
        <Field
          label="Report it as"
          hint="A share is what a target is usually set against: 90% completed, not 900 completed."
        >
          <select
            className="input"
            value={percentOf}
            onChange={(event) => setPercentOf(event.target.value as PercentOf)}
          >
            <option value="">A count</option>
            <option value="all_rows">A percentage of every record</option>
            {variable && (
              <option value="answered">
                A percentage of the records that answered {variable}
              </option>
            )}
          </select>
        </Field>
      )}

      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field
          label="Break down by"
          hint="Optional. Shows the indicator per region, team, etc. - and can go on a dashboard as a chart."
        >
          <select
            className="input"
            value={breakdown}
            onChange={(event) => setBreakdown(event.target.value)}
          >
            <option value="">No breakdown</option>
            {groupable.map((v) => (
              <option key={v.name} value={v.name}>
                {v.label ? `${v.name} — ${v.label}` : v.name}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={isPercent ? 'Target (%)' : 'Target value'}
          hint={isPercent ? 'e.g. 90 for nine in ten' : 'Used for the progress bar'}
        >
          <input
            className="input"
            type="number"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          />
        </Field>
        <Field label="Direction">
          <select
            className="input"
            value={direction}
            onChange={(event) => setDirection(event.target.value as Direction)}
          >
            <option value="higher_is_better">Higher is better</option>
            <option value="lower_is_better">Lower is better</option>
            <option value="neutral">Neither</option>
          </select>
        </Field>
        <div />
        <Field label={isPercent ? 'Warning threshold (%)' : 'Warning threshold'}>
          <input
            className="input"
            type="number"
            value={warning}
            onChange={(event) => setWarning(event.target.value)}
          />
        </Field>
        <Field label={isPercent ? 'Critical threshold (%)' : 'Critical threshold'}>
          <input
            className="input"
            type="number"
            value={critical}
            onChange={(event) => setCritical(event.target.value)}
          />
        </Field>
      </div>
      <p className="text-xs text-ink-500">
        With "higher is better", the indicator turns amber at or below the warning threshold and
        red at or below the critical one. The logic reverses for "lower is better".
      </p>
    </Modal>
  )
}
