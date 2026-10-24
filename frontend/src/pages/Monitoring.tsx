import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import ReactECharts from '@/components/ReactECharts'
import { measurable } from '@/lib/measures'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { buildSparkline, STATUS_COLORS } from '@/lib/charts'
import { by } from '@/lib/collections'
import { quotaSummary } from '@/lib/quotas'
import { orderBreakdown } from '@/lib/breakdown-order'
import { formatNumber, formatValue, relativeTime } from '@/lib/format'
import type {
  Aggregation,
  Dataset,
  Direction,
  FilterGroup,
  Formula,
  FormulaPart,
  Indicator,
  IndicatorValue,
} from '@/lib/types'
import ChartCard from '@/components/ChartCard'
import ProjectFilter, { datasetProjectParam, projectParam } from '@/components/ProjectFilter'
import FilterBuilder, { emptyFilter } from '@/components/FilterBuilder'
import { allReady, FormulaBuilder } from '@/components/monitoring/FormulaBuilder'
import type { BadgeTone } from '@/components/ui'
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

// On track carries no glyph: the state nobody has to act on should not be
// decorated, and the three that do keep theirs.
const STATE: Record<string, { tone: BadgeTone; icon?: string; label: string }> = {
  ok: { tone: 'success', label: 'On track' },
  warning: { tone: 'warning', icon: '▲', label: 'Watch' },
  critical: { tone: 'danger', icon: '■', label: 'Critical' },
  unknown: { tone: 'neutral', icon: '-', label: 'No data' },
}

export default function Monitoring() {
  const { can } = useAuth()
  const toast = useToast()
  const ask = useDialog()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Indicator | null>(null)
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
        title="Indicators"
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
                onEdit={definition ? () => setEditing(definition) : undefined}
                onDelete={async () => {
                  const sure = await ask.confirm({
                    title: `Delete \u201C${value.name}\u201D?`,
                    message: 'Its history goes with it, and any alert rule watching it stops.',
                    confirmLabel: 'Delete indicator',
                    tone: 'danger',
                  })
                  if (sure) remove.mutate(value.indicator_id)
                }}
              />
            )
          })}
        </div>
      )}

      {creating && <IndicatorModal project={project} onClose={() => setCreating(false)} />}
      {editing && (
        <IndicatorModal indicator={editing} project={project} onClose={() => setEditing(null)} />
      )}
    </>
  )
}

function IndicatorCard({
  value,
  definition,
  canManage,
  onEdit,
  onDelete,
}: {
  value: IndicatorValue
  definition?: Indicator
  canManage: boolean
  onEdit?: () => void
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
          {canManage && onEdit && (
            // A threshold set before fieldwork started is a guess, and the
            // whole indicator had to be deleted and rebuilt to correct it.
            <button
              className="btn-ghost btn-sm text-ink-500"
              onClick={onEdit}
              title="Edit this indicator"
            >
              ✎
            </button>
          )}
          {canManage && (
            <button className="btn-ghost btn-sm text-red-600" onClick={onDelete}>
              ✕
            </button>
          )}
        </>
      }
    >
      {value.error && (
        <p className="aero-pane aero-pane-warn mb-3 px-3 py-2 pl-4 text-xs text-amber-900 dark:text-amber-200">
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
            {value.progress_percent?.toFixed(0) ?? '-'}% of target{' '}
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
          {(() => {
            const progress = breakdown.data.breakdown_progress ?? {}
            // Each group beside its own quota, not beside the headline: the
            // headline is what the quotas add up to, so a group measured
            // against it reads as far behind whatever it has actually done.
            const quoted = Object.keys(breakdown.data!.breakdown).some(
              (key) => (progress[key]?.target ?? null) !== null,
            )
            // Furthest from its own quota first, which is the question this
            // page exists to answer. The dashboard tile offers the other
            // orders; here there is one chart and it should open on the
            // areas that need somebody.
            const rows = orderBreakdown(
              Object.entries(breakdown.data!.breakdown),
              progress,
            ).map(([key, val]) =>
              quoted ? [key, val, progress[key]?.target ?? null] : [key, val],
            )
            return (
              <ChartCard
                showToggle={false}
                chartType="horizontal_bar"
                height={Math.min(420, Math.max(200, rows.length * 26))}
                result={{
                  columns: [
                    {
                      name: 'group',
                      label: definition?.breakdown_variable ?? 'Group',
                      type: 'dimension',
                      data_type: 'text',
                    },
                    { name: 'value', label: value.name, type: 'measure', data_type: 'number' },
                    ...(quoted
                      ? [
                          {
                            name: 'target',
                            label: 'Its own quota',
                            type: 'measure' as const,
                            data_type: 'number' as const,
                          },
                        ]
                      : []),
                  ],
                  rows,
                  row_count: rows.length,
                  truncated: false,
                  sql: '',
                  duration_ms: 0,
                }}
              />
            )
          })()}
          {breakdown.data.breakdown_truncated && (
            <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
              This breakdown has more groups than one answer reports, so what is
              drawn here is the first of them.
            </p>
          )}
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
  // Not one aggregate at all: several, under names, combined by a sum. Most
  // of what a survey office reports is a rate between two different counts,
  // and none of the rows above can be two counts.
  {
    value: 'formula',
    label: 'A formula over several counts',
    agg: 'count',
    needsVariable: false,
    numericOnly: false,
  },
]

type MeasureKind =
  | 'records'
  | 'answered'
  | 'sum'
  | 'mean'
  | 'median'
  | 'distinct'
  | 'formula'
type PercentOf = '' | 'all_rows' | 'answered'

/** Which of the measures above produced this indicator's spec.
 *
 *  An indicator stores a query, not the choice that built it, so editing one
 *  means reading the choice back out: the aggregate plus whether it names a
 *  variable is enough to tell them apart.
 */
function measureKindOf(indicator: Indicator): MeasureKind {
  // A formula is the definition where there is one, so it is what the form
  // opens on - the single measure underneath is left over and not read.
  if ((indicator.formula as Formula | undefined)?.parts?.length) return 'formula'
  const measure = indicator.spec?.measures?.[0]
  if (!measure) return 'records'
  const named = Boolean(measure.variable)
  const match = MEASURES.find((m) => m.agg === measure.agg && m.needsVariable === named)
  return match?.value ?? 'records'
}

/**
 * What the per-group quotas add up to, said under the list of them.
 *
 * Silent until at least one is set, because a form that says "0 of 15,040" to
 * somebody who has not started is nagging rather than helping.
 */
function QuotaTotal({
  targets,
  headline,
}: {
  targets: Record<string, string>
  headline: string
}) {
  const summary = quotaSummary(targets, headline)
  if (!summary.set) return null

  const groups = `${summary.set} group${summary.set === 1 ? '' : 's'}`
  const adding = `${groups} with a quota, adding up to ${formatNumber(summary.total)}`
  if (summary.headline === null) {
    return <p className="mt-2 text-xs text-ink-500 dark:text-dark-500">{adding}.</p>
  }

  const off = summary.difference ?? 0
  const matches = off === 0
  return (
    <p className={`mt-2 text-xs ${matches ? 'text-ink-500 dark:text-dark-500' : 'text-amber-700 dark:text-amber-400'}`}>
      {adding}
      {matches
        ? `, which is the overall target.`
        : `, ${formatNumber(Math.abs(off))} ${off > 0 ? 'more than' : 'short of'} the overall ${formatNumber(summary.headline)}. That is allowed - the quotas you set are the ones that are judged - but it is usually a typo.`}
    </p>
  )
}


function IndicatorModal({
  indicator,
  project,
  onClose,
}: {
  indicator?: Indicator
  /** The project filter the page is under: null is every project. */
  project?: string | null
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const editing = Boolean(indicator)
  const [datasetId, setDatasetId] = useState(indicator?.dataset_id ?? '')
  const [name, setName] = useState(indicator?.name ?? '')
  const [kind, setKind] = useState<MeasureKind>(
    indicator ? measureKindOf(indicator) : 'records',
  )
  const [variable, setVariable] = useState(
    indicator?.spec?.measures?.[0]?.variable ?? '',
  )
  const [where, setWhere] = useState<FilterGroup>(
    indicator?.spec?.filters ?? emptyFilter(),
  )
  const [percentOf, setPercentOf] = useState<PercentOf>(indicator?.percent_of ?? '')
  // The parts of a formula and the sum over them, where the indicator is
  // written that way. Kept beside the single measure rather than instead of
  // it, so switching back and forth does not throw either away.
  const [parts, setParts] = useState<FormulaPart[]>(
    () => (indicator?.formula as Formula | undefined)?.parts ?? [],
  )
  const [expression, setExpression] = useState(
    (indicator?.formula as Formula | undefined)?.expression ?? '',
  )
  // A rate written as "× 100" is a percentage and a ratio is not, and only
  // the person writing it knows which. It decides how the tile prints the
  // number, nothing else.
  const [formulaPercent, setFormulaPercent] = useState(
    indicator?.value_format === 'percent',
  )
  const [breakdown, setBreakdown] = useState(indicator?.breakdown_variable ?? '')
  const [target, setTarget] = useState(
    indicator?.target_value === null || indicator?.target_value === undefined
      ? ''
      : String(indicator.target_value),
  )
  const [warning, setWarning] = useState(
    indicator?.warning_threshold === null || indicator?.warning_threshold === undefined
      ? ''
      : String(indicator.warning_threshold),
  )
  const [critical, setCritical] = useState(
    indicator?.critical_threshold === null || indicator?.critical_threshold === undefined
      ? ''
      : String(indicator.critical_threshold),
  )
  const [direction, setDirection] = useState<Direction>(
    indicator?.direction ?? 'higher_is_better',
  )
  // Kept as typed text rather than numbers so a half-entered "12" is not
  // rounded away under the cursor, and an emptied box means "no quota here"
  // rather than zero.
  // Either a shared set or this indicator's own quotas, never both: two lists
  // half-applied is a number nobody can account for.
  const [targetSet, setTargetSet] = useState(indicator?.target_set_id ?? '')
  const [categoryTargets, setCategoryTargets] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(indicator?.breakdown_targets ?? {}).map(([k, v]) => [k, String(v)]),
    ),
  )

  // Under a project, only that project's data: offering every dataset on the
  // server made "new indicator" a list to hunt through, and an indicator built
  // from the wrong one silently belongs to the wrong project, because an
  // indicator lives wherever its dataset lives.
  const scope = datasetProjectParam(project ?? null)
  const datasets = useQuery({
    queryKey: ['datasets', 'ready', scope],
    queryFn: () => api.getAll<Dataset>(`/datasets?status=ready${scope}`),
  })
  const dataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: Boolean(datasetId),
  })

  // An indicator being edited keeps its own dataset on the list even when that
  // dataset is not in what came back - a project past the two hundred this
  // asks for, or one filtered out. Dropping it would leave the box blank over
  // a value that is still set, which reads as "no dataset" and is a lie about
  // what saving would do.
  const datasetChoices = [
    ...(datasets.data?.items ?? []),
    ...(dataset.data && !(datasets.data?.items ?? []).some((d) => d.id === dataset.data.id)
      ? [dataset.data]
      : []),
  ]

  // The categories a per-category target can be set for. Read from the data
  // rather than typed, so a quota cannot be attached to a spelling that does
  // not occur - "Northern" against a column that says "North".
  const targetSets = useQuery({
    queryKey: ['target-sets', datasetId],
    queryFn: () =>
      api.get<
        { id: string; name: string; variable: string; categories: number; total: number }[]
      >(`/monitoring/target-sets?dataset_id=${datasetId}`),
    enabled: Boolean(datasetId),
  })

  const categories = useQuery({
    queryKey: ['values', datasetId, breakdown],
    queryFn: () =>
      api.get<{ value: string; label: string; count: number }[]>(
        `/datasets/${datasetId}/variables/${encodeURIComponent(breakdown)}/values?limit=100`,
      ),
    enabled: Boolean(datasetId && breakdown),
  })

  const variables = dataset.data?.variables ?? []
  // Anything stored as a number, not only what the importer judged to be
  // a quantity: see lib/measures.
  const numeric = measurable(variables)
  const groupable = variables.filter((v) => v.var_type === 'categorical' || v.n_unique <= 100)
  const measure = MEASURES.find((m) => m.value === kind)!
  const choices = measure.numericOnly ? numeric : variables
  const isPercent = percentOf !== ''
  const usingFormula = kind === 'formula'

  // Only a counted measure has a meaningful share: the mean of a variable is
  // not a portion of anything, and dividing it by a row count says nothing.
  const canBePercent = kind === 'records' || kind === 'answered'

  const create = useMutation({
    mutationFn: () => {
      const body = {
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
        // Arithmetic over named parts, or nothing at all: an empty formula
        // leaves the indicator defined by the single measure above, and
        // clears one that was there.
        formula: usingFormula
          ? { expression, parts }
          : { expression: '', parts: [] },
        // A percentage says so in how it is written, rather than in a unit
        // typed by hand that the tile would then print twice.
        value_format: usingFormula
          ? formulaPercent
            ? 'percent'
            : 'number'
          : isPercent && canBePercent
            ? 'percent'
            : 'number',
        target_value: target ? Number(target) : null,
        // Only the categories actually given a quota. An empty box means the
        // category falls back to the headline target, which is not the same
        // as a quota of zero.
        breakdown_targets: breakdown
          ? Object.fromEntries(
              Object.entries(categoryTargets)
                .filter(([, value]) => value.trim() !== '' && !Number.isNaN(Number(value)))
                .map(([category, value]) => [category, Number(value)]),
            )
          : {},
        target_set_id: breakdown ? targetSet : '',
        warning_threshold: warning ? Number(warning) : null,
        critical_threshold: critical ? Number(critical) : null,
        direction,
      }
      return indicator
        ? api.patch(`/monitoring/indicators/${indicator.id}`, body)
        : api.post('/monitoring/indicators', body)
    },
    onSuccess: () => {
      toast.push(editing ? 'Indicator saved' : 'Indicator created', 'success')
      queryClient.invalidateQueries({ queryKey: ['indicator-values'] })
      queryClient.invalidateQueries({ queryKey: ['indicators'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const ready =
    name &&
    datasetId &&
    (usingFormula
      ? Boolean(expression.trim()) && parts.length > 0 && allReady(parts)
      : !measure.needsVariable || Boolean(variable))

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? `Edit ${indicator!.name}` : 'New indicator'}
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
            {editing ? 'Save changes' : 'Create indicator'}
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
            data-suggest=""
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
            {datasetChoices.map((item) => (
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
        {measure.needsVariable && !usingFormula && (
          <Field label={measure.numericOnly ? 'Numeric variable' : 'Variable'}>
            <select
              className="input"
              value={variable}
              onChange={(event) => setVariable(event.target.value)}
            >
              <option value="">Choose a variable…</option>
              {choices.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.label ? `${v.name} - ${v.label}` : v.name}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>

      {usingFormula ? (
        <Field
          label="The parts and the sum"
          hint="Each part is counted on its own terms. The formula combines them - a rate is one part over another, times a hundred."
        >
          {datasetId ? (
            <FormulaBuilder
              datasetId={datasetId}
              variables={variables}
              parts={parts}
              expression={expression}
              format={formulaPercent ? 'percent' : 'number'}
              onParts={setParts}
              onExpression={setExpression}
            />
          ) : (
            <p className="text-xs text-ink-400">Choose a dataset first.</p>
          )}
        </Field>
      ) : (
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
      )}

      {usingFormula && (
        <Field
          label="Report it as"
          hint="Only how the number is printed: a rate written with a hundred in it is a percentage, a ratio is not."
        >
          <select
            className="input"
            value={formulaPercent ? 'percent' : 'number'}
            onChange={(event) => setFormulaPercent(event.target.value === 'percent')}
          >
            <option value="number">A number</option>
            <option value="percent">A percentage</option>
          </select>
        </Field>
      )}

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
                {v.label ? `${v.name} - ${v.label}` : v.name}
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
        {breakdown && (
          <Field
            label="Where the quotas come from"
            hint="A target set is one list kept in one place and read by every indicator judged against it - which is what a census needs, where the quotas are two thousand enumeration areas. Typing them here instead is right for four provinces."
          >
            <select
              className="input"
              value={targetSet}
              onChange={(event) => setTargetSet(event.target.value)}
            >
              <option value="">Quotas typed in below</option>
              {(targetSets.data ?? [])
                .filter((one) => !one.variable || one.variable === breakdown)
                .map((one) => (
                  <option key={one.id} value={one.id}>
                    {one.name} ({formatNumber(one.categories)} groups, {formatNumber(one.total)})
                  </option>
                ))}
            </select>
          </Field>
        )}

        {breakdown && !targetSet && (categories.data?.length ?? 0) > 0 && (
        <Field
          label="Target for each group"
          hint="Optional, and each one is that group's own quota rather than a share of the overall target. A group left empty is reported but not judged: the overall target belongs to all of them together, so measuring one group against it says nothing."
        >
          <div className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
            {/* In the order a reader looks them up in - a list of enumeration
                areas arrives in whatever order the query answered in, which
                is no order at all once there are sixty of them. */}
            {[...(categories.data ?? [])]
              .sort(by((option) => String(option.label || option.value)))
              .map((option) => {
                // Keyed by the label, because that is what the breakdown
                // reports and so what a quota is looked up by. Keyed by the
                // code - which is what this list offers - an area labelled
                // "0405" behind the code 405 had a quota that was never
                // applied, with nothing on screen saying so.
                const key = String(option.label || option.value)
                return (
                  <label key={key} className="flex items-center gap-2 text-sm text-ink-700 dark:text-dark-700">
                    <span className="min-w-0 flex-1 truncate" title={option.label || key}>
                      {option.label || key}
                    </span>
                    <input
                      className="input input-sm w-28"
                      type="number"
                      placeholder="none"
                      aria-label={`Target for ${option.label || key}`}
                      value={categoryTargets[key] ?? ''}
                      onChange={(event) =>
                        setCategoryTargets({ ...categoryTargets, [key]: event.target.value })
                      }
                    />
                  </label>
                )
              })}
          </div>
        </Field>
      )}
      {/* The quotas are the overall target, divided up. Said under the list
          because sixty boxes is exactly where one gets mistyped, and nothing
          else would ever mention it. Outside the field so it reads after the
          explanation rather than between the boxes and it. */}
      {breakdown && !targetSet && (categories.data?.length ?? 0) > 0 && (
        <div className="-mt-2 mb-4">
          <QuotaTotal targets={categoryTargets} headline={target} />
        </div>
      )}

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
