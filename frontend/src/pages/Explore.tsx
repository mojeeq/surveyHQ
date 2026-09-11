import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, downloadFile } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber } from '@/lib/format'
import type {
  Aggregation,
  Chart,
  ChartType,
  CrosstabRequest,
  CrosstabResult,
  Dataset,
  DateGrain,
  Dimension,
  FilterGroup,
  Measure,
  MultiSelectGroup,
  MultiSelectRequest,
  Page,
  Project,
  QueryResult,
  QuerySpec,
  Variable,
} from '@/lib/types'
import ChartCard from '@/components/ChartCard'
import { BOX_MEASURES } from '@/lib/charts'
import type { BuildOptions } from '@/lib/charts'
import CrosstabTable from '@/components/CrosstabTable'
import FilterBuilder, { emptyFilter } from '@/components/FilterBuilder'
import {
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Spinner,
  Tabs,
} from '@/components/ui'

const AGGREGATIONS: { value: Aggregation; label: string; needsVariable: boolean }[] = [
  { value: 'count', label: 'Count', needsVariable: false },
  { value: 'share', label: 'Share of total (%)', needsVariable: false },
  { value: 'sum', label: 'Sum', needsVariable: true },
  { value: 'mean', label: 'Mean', needsVariable: true },
  { value: 'median', label: 'Median', needsVariable: true },
  { value: 'min', label: 'Minimum', needsVariable: true },
  { value: 'max', label: 'Maximum', needsVariable: true },
  { value: 'stddev', label: 'Std deviation', needsVariable: true },
  { value: 'p25', label: '25th percentile', needsVariable: true },
  { value: 'p75', label: '75th percentile', needsVariable: true },
  { value: 'count_distinct', label: 'Distinct count', needsVariable: true },
]

const CHART_TYPES: { value: ChartType; label: string }[] = [
  { value: 'bar', label: 'Bar' },
  { value: 'horizontal_bar', label: 'Horizontal bar' },
  { value: 'stacked_bar', label: 'Stacked bar' },
  { value: 'horizontal_stacked_bar', label: 'Horizontal stacked bar' },
  { value: 'population_pyramid', label: 'Population pyramid' },
  { value: 'line', label: 'Line' },
  { value: 'area', label: 'Area' },
  { value: 'donut', label: 'Donut' },
  { value: 'pie', label: 'Pie' },
  { value: 'scatter', label: 'Scatter' },
  { value: 'boxplot', label: 'Box plot' },
  { value: 'heatmap', label: 'Heatmap' },
  { value: 'table', label: 'Table' },
]

/** How a variable reads in a picker.
 *
 *  A variable with a value per row will tabulate to as many rows as the limit
 *  allows, which is fine when it is what you asked for and a surprise when it
 *  is not. Saying how many distinct values it holds is the difference.
 */
function optionLabel(v: Variable): string {
  const named = v.label ? `${v.name} - ${v.label}` : v.name
  return v.n_unique > 200 ? `${named} (${formatNumber(v.n_unique)} values)` : named
}

type Mode = 'aggregate' | 'crosstab' | 'multiselect'

/** Which builder a saved chart was made in, so editing reopens it there.
 *
 *  A cross-tabulation says so in its chart type; a multiple-select does not,
 *  because it is drawn as an ordinary bar. What marks it is the spec: it holds
 *  the columns the question was spread across instead of a query.
 */
function modeOf(chart: Chart): Mode {
  if (chart.chart_type === 'crosstab') return 'crosstab'
  if (chart.spec?.multiselect) return 'multiselect'
  return 'aggregate'
}

/** The chart being edited, but only for the builder that made it. */
function openedIn(mode: Mode, chart?: Chart): Chart | undefined {
  return chart && modeOf(chart) === mode ? chart : undefined
}

export default function Explore() {
  const [params, setParams] = useSearchParams()
  const toast = useToast()
  const { can } = useAuth()
  const [mode, setMode] = useState<Mode>('aggregate')

  const datasets = useQuery({
    queryKey: ['datasets', 'all'],
    queryFn: () => api.get<Page<Dataset>>('/datasets?limit=200&status=ready'),
  })
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<Project[]>('/projects'),
  })

  // Both live in the URL, so a link to an analysis lands on the same two
  // choices rather than resetting to whatever happens to be first.
  const projectId = params.get('project') ?? ''
  const inProject = useMemo(
    () =>
      (datasets.data?.items ?? []).filter((item) =>
        projectId === ''
          ? true
          : projectId === 'none'
            ? item.project_id === null
            : item.project_id === projectId,
      ),
    [datasets.data, projectId],
  )

  // Editing a saved chart opens it here, which is where its query was built
  // in the first place. Everything is prefilled, so "change the variable" is
  // changing the variable rather than rebuilding the chart from memory.
  const editingId = params.get('chart') ?? ''
  const editing = useQuery({
    queryKey: ['chart', editingId],
    queryFn: () => api.get<Chart>(`/dashboards/charts/${editingId}`),
    enabled: Boolean(editingId),
  })

  // A saved chart is edited in whichever builder made it, so opening one has
  // to switch to that tab first.
  useEffect(() => {
    if (editing.data) setMode(modeOf(editing.data))
  }, [editing.data])

  const requested = editing.data?.dataset_id || (params.get('dataset') ?? '')
  // A dataset from another project stops being a valid choice the moment the
  // project filter changes, so fall back rather than showing an empty picker.
  const datasetId = inProject.some((item) => item.id === requested)
    ? requested
    : (inProject[0]?.id ?? '')

  const dataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: Boolean(datasetId),
  })

  const variables = dataset.data?.variables ?? []
  // Every variable can be grouped on, including the ones with a value per row.
  // Hiding them was meant to keep a 20,000-row tabulation out of the way, but
  // it hid interview__key - and "one row per interview, with these columns" is
  // a thing people legitimately want to tabulate. The count travels with the
  // name instead, and the row limit still decides how much comes back.
  const groupable = useMemo(() => variables.filter((v) => !v.is_hidden), [variables])
  const numeric = useMemo(() => variables.filter((v) => v.var_type === 'numeric'), [variables])

  if (datasets.isLoading) return <Loading />
  if (!datasets.data?.items.length) {
    return (
      <Card>
        <EmptyState
          icon="▤"
          title="No datasets ready to analyse"
          description="Upload a data file or import from a Survey Solutions server first."
        />
      </Card>
    )
  }

  return (
    <>
      <PageHeader
        title={editing.data ? `Editing “${editing.data.name}”` : 'Explore'}
        description={
          editing.data
            ? 'Change the grouping, the measure, the filters or the chart type. Saving writes back to this chart, so every dashboard showing it follows.'
            : 'Build tabulations and charts against any dataset.'
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {editing.data && (
              <button
                className="btn-secondary"
                onClick={() => {
                  const next = new URLSearchParams(params)
                  next.delete('chart')
                  setParams(next)
                }}
              >
                Stop editing
              </button>
            )}
            <select
              className="input w-52"
              value={projectId}
              onChange={(event) =>
                setParams(
                  event.target.value ? { project: event.target.value } : {},
                )
              }
            >
              <option value="">All projects</option>
              <option value="none">Shared area</option>
              {projects.data?.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <select
              className="input w-64"
              value={datasetId}
              disabled={!inProject.length}
              onChange={(event) =>
                setParams(
                  projectId
                    ? { project: projectId, dataset: event.target.value }
                    : { dataset: event.target.value },
                )
              }
            >
              {inProject.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
        }
      />

      <Tabs
        tabs={[
          { id: 'aggregate', label: 'Tabulate & chart' },
          { id: 'crosstab', label: 'Cross-tabulation' },
          { id: 'multiselect', label: 'Tick all that apply' },
        ]}
        active={mode}
        onChange={(id) => setMode(id as Mode)}
      />

      {!inProject.length ? (
        <Card className="mt-4">
          <EmptyState
            icon="▤"
            title="Nothing to analyse in this project"
            description="Assign a dataset to it from the Datasets page, or upload straight into it."
          />
        </Card>
      ) : dataset.isLoading ? (
        <Loading />
      ) : !dataset.data ? (
        <ErrorNote error={new Error('Dataset could not be loaded')} />
      ) : mode === 'aggregate' ? (
        <AggregateBuilder
          key={editingId || datasetId}
          datasetId={datasetId}
          datasetName={dataset.data.name}
          groupable={groupable}
          numeric={numeric}
          allVariables={variables}
          canSave={can('analyst')}
          editing={openedIn('aggregate', editing.data)}
          onSaved={() => toast.push('Chart saved', 'success')}
        />
      ) : mode === 'crosstab' ? (
        <CrosstabBuilder
          key={editingId || datasetId}
          datasetId={datasetId}
          datasetName={dataset.data.name}
          groupable={groupable}
          numeric={numeric}
          allVariables={variables}
          canSave={can('analyst')}
          editing={openedIn('crosstab', editing.data)}
        />
      ) : (
        <MultiSelectBuilder
          key={editingId || datasetId}
          datasetId={datasetId}
          datasetName={dataset.data.name}
          allVariables={variables}
          canSave={can('analyst')}
          editing={openedIn('multiselect', editing.data)}
        />
      )}
    </>
  )
}

type VariableList = Dataset['variables']

/**
 * What a box plot asks for in place of a list of measures.
 *
 * One variable, because the five numbers a box is drawn from are five
 * summaries of the same thing - so a list of measures would be a list with
 * only one right answer in it.
 *
 * The note underneath is there because "box plot" does not say which box plot.
 * These whiskers reach the smallest and largest value in the group rather than
 * one and a half times the box, so nothing sits outside them as an outlier and
 * nothing is quietly left out of the picture. Somebody comparing this against
 * a box drawn in R has to be told that.
 */
function BoxMeasure({
  numeric,
  variable,
  weight,
  onVariable,
  onWeight,
}: {
  numeric: NonNullable<VariableList>
  variable: string
  weight: string | null
  onVariable: (next: string) => void
  onWeight: (next: string | null) => void
}) {
  return (
    <div className="space-y-2 rounded-card border border-ink-200 p-3">
      <select
        className="input py-1.5 text-xs"
        aria-label="Variable to summarise"
        value={variable}
        onChange={(event) => onVariable(event.target.value)}
      >
        {numeric.map((v) => (
          <option key={v.name} value={v.name}>
            {optionLabel(v)}
          </option>
        ))}
      </select>
      <select
        className="input py-1.5 text-xs"
        aria-label="Weight"
        value={weight ?? ''}
        onChange={(event) => onWeight(event.target.value || null)}
      >
        <option value="">Unweighted</option>
        {numeric.map((v) => (
          <option key={v.name} value={v.name}>
            Weight by {v.name}
          </option>
        ))}
      </select>
      <p className="text-xs text-ink-500 dark:text-dark-500">
        One box for each group, drawn from{' '}
        {BOX_MEASURES.map((measure) => measure.label.toLowerCase()).join(', ')}. The whiskers
        reach the smallest and largest value in the group, so nothing is left outside them.
      </p>
    </div>
  )
}

function AggregateBuilder({
  datasetId,
  datasetName,
  groupable,
  numeric,
  allVariables,
  canSave,
  editing,
  onSaved,
}: {
  datasetId: string
  datasetName: string
  groupable: NonNullable<VariableList>
  numeric: NonNullable<VariableList>
  allVariables: NonNullable<VariableList>
  canSave: boolean
  /** The saved chart being edited, if this was opened from one. */
  editing?: Chart
  onSaved: () => void
}) {
  const toast = useToast()
  const [dimensions, setDimensions] = useState<Dimension[]>([])
  const [measures, setMeasures] = useState<Measure[]>([{ agg: 'count', alias: 'count' }])
  const [filters, setFilters] = useState<FilterGroup>(emptyFilter())
  const [chartType, setChartType] = useState<ChartType>('bar')
  /**
   * The variable a box plot summarises, and the weight it is summarised under.
   *
   * Kept apart from the measure list rather than written into it. A box plot is
   * five aggregations of one variable, and putting those five in the list would
   * mean rewriting it every time the chart type changed - and leaving somebody
   * who switched to a bar chart and back with five bars per category. Held here,
   * the two builders do not disturb each other, and the five are written only
   * into the query that is sent.
   */
  const [boxVariable, setBoxVariable] = useState('')
  const [boxWeight, setBoxWeight] = useState<string | null>(null)
  const [display, setDisplay] = useState<BuildOptions>({ sort: 'value_desc' })
  const [limit, setLimit] = useState(50)
  const [result, setResult] = useState<QueryResult | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [showSql, setShowSql] = useState(false)
  /** Set when a chart's saved query has just been loaded and wants running. */
  const [pending, setPending] = useState(false)

  // Reset the builder whenever the dataset changes; variable names differ.
  useEffect(() => {
    setDimensions([])
    setMeasures([{ agg: 'count', alias: 'count' }])
    setBoxVariable('')
    setBoxWeight(null)
    setFilters(emptyFilter())
    setResult(null)
  }, [datasetId])

  // A chart opened for editing fills the builder with what it was built from.
  useEffect(() => {
    if (!editing) return
    const saved = (editing.spec?.query ?? editing.spec) as QuerySpec | undefined
    if (!saved) return
    setDimensions(saved.dimensions ?? [])
    setMeasures(saved.measures ?? [{ agg: 'count', alias: 'count' }])
    // A saved box plot carries the five; which variable they are five of is
    // read back off any one of them.
    const middle = saved.measures?.find((measure) => measure.alias === 'box_median')
    if (middle) {
      setBoxVariable(middle.variable ?? '')
      setBoxWeight(middle.weight ?? null)
    }
    setFilters(saved.filters ?? emptyFilter())
    setLimit(saved.limit ?? 50)
    setChartType(editing.chart_type as ChartType)
    setDisplay((editing.spec?.options as BuildOptions) ?? { sort: 'value_desc' })
    setPending(true)
  }, [editing])

  // Run once the prefilled query has reached the state the request is built
  // from, rather than from inside the effect that fills it in.
  useEffect(() => {
    if (!pending || !dimensions.length) return
    setPending(false)
    run.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, dimensions])

  const isBox = chartType === 'boxplot'
  /** Falls back to the first numeric variable until one has been picked. */
  const boxColumn = boxVariable || numeric[0]?.name || ''
  const queryMeasures: Measure[] = isBox
    ? BOX_MEASURES.map((measure) => ({
        agg: measure.agg as Aggregation,
        variable: boxColumn,
        alias: measure.alias,
        weight: boxWeight,
      }))
    : measures

  const spec: QuerySpec = {
    dimensions,
    measures: queryMeasures,
    filters,
    // The boxes are ranked by where their middle sits, not by their smallest
    // number: ordering groups by their minimum puts the widest spread last.
    sort: isBox
      ? [{ field: 'box_median', direction: 'desc' }]
      : measures.length
        ? [{ field: measures[0].alias || measures[0].agg, direction: 'desc' }]
        : [],
    limit,
    use_labels: true,
  }

  const run = useMutation({
    mutationFn: () => api.post<QueryResult>('/analytics/query', { dataset_id: datasetId, spec }),
    onSuccess: setResult,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const suggestions = useQuery({
    queryKey: ['suggestions', datasetId],
    queryFn: () => api.post<any[]>(`/analytics/datasets/${datasetId}/suggest`),
  })

  return (
    <div className="mt-4 grid gap-6 lg:grid-cols-[330px_1fr]">
      <div className="space-y-4">
        <Card title="Group by">
          {dimensions.map((dimension, index) => {
            const variable = allVariables.find((v) => v.name === dimension.variable)
            return (
              <div key={index} className="mb-3 rounded-card border border-ink-200 p-3">
                <div className="flex items-center gap-2">
                  <select
                    className="input flex-1 py-1.5 text-xs"
                    value={dimension.variable}
                    onChange={(event) =>
                      setDimensions(
                        dimensions.map((d, i) =>
                          i === index ? { ...d, variable: event.target.value, grain: null } : d,
                        ),
                      )
                    }
                  >
                    {groupable.map((v) => (
                      <option key={v.name} value={v.name}>
                        {optionLabel(v)}
                      </option>
                    ))}
                  </select>
                  <button
                    className="btn-ghost btn-sm text-red-600"
                    onClick={() => setDimensions(dimensions.filter((_, i) => i !== index))}
                  >
                    ✕
                  </button>
                </div>
                {variable?.var_type === 'datetime' && (
                  <select
                    className="input mt-2 py-1.5 text-xs"
                    value={dimension.grain ?? 'day'}
                    onChange={(event) =>
                      setDimensions(
                        dimensions.map((d, i) =>
                          i === index ? { ...d, grain: event.target.value as DateGrain } : d,
                        ),
                      )
                    }
                  >
                    {['day', 'week', 'month', 'quarter', 'year'].map((grain) => (
                      <option key={grain} value={grain}>
                        By {grain}
                      </option>
                    ))}
                  </select>
                )}
                {variable?.var_type === 'numeric' && (
                  <input
                    className="input mt-2 py-1.5 text-xs"
                    type="number"
                    placeholder="Bin width (optional)"
                    value={dimension.bin_width ?? ''}
                    onChange={(event) =>
                      setDimensions(
                        dimensions.map((d, i) =>
                          i === index
                            ? { ...d, bin_width: event.target.value ? Number(event.target.value) : null }
                            : d,
                        ),
                      )
                    }
                  />
                )}
                {index === 0 && (
                  <input
                    className="input mt-2 py-1.5 text-xs"
                    type="number"
                    placeholder="Keep top N (rest become Other)"
                    value={dimension.limit ?? ''}
                    onChange={(event) =>
                      setDimensions(
                        dimensions.map((d, i) =>
                          i === index
                            ? { ...d, limit: event.target.value ? Number(event.target.value) : null }
                            : d,
                        ),
                      )
                    }
                  />
                )}
              </div>
            )
          })}
          {dimensions.length < 2 && (
            <button
              className="btn-secondary btn-sm w-full"
              onClick={() =>
                setDimensions([...dimensions, { variable: groupable[0]?.name ?? '' }])
              }
              disabled={!groupable.length}
            >
              + Add grouping
            </button>
          )}
        </Card>

        <Card title={isBox ? 'Summarise' : 'Measure'}>
          {isBox ? (
            <BoxMeasure
              numeric={numeric}
              variable={boxColumn}
              weight={boxWeight}
              onVariable={setBoxVariable}
              onWeight={setBoxWeight}
            />
          ) : (
            <>
            {measures.map((measure, index) => {
              const definition = AGGREGATIONS.find((a) => a.value === measure.agg)
              return (
                <div key={index} className="mb-3 space-y-2 rounded-card border border-ink-200 p-3">
                  <div className="flex items-center gap-2">
                    <select
                      className="input flex-1 py-1.5 text-xs"
                      value={measure.agg}
                      onChange={(event) => {
                        const agg = event.target.value as Aggregation
                        const needs = AGGREGATIONS.find((a) => a.value === agg)?.needsVariable
                        setMeasures(
                          measures.map((m, i) =>
                            i === index
                              ? {
                                  ...m,
                                  agg,
                                  variable: needs ? m.variable || numeric[0]?.name : null,
                                  alias: needs ? `${agg}_${m.variable || numeric[0]?.name}` : agg,
                                }
                              : m,
                          ),
                        )
                      }}
                    >
                      {AGGREGATIONS.map((a) => (
                        <option key={a.value} value={a.value}>
                          {a.label}
                        </option>
                      ))}
                    </select>
                    {measures.length > 1 && (
                      <button
                        className="btn-ghost btn-sm text-red-600"
                        onClick={() => setMeasures(measures.filter((_, i) => i !== index))}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                  {definition?.needsVariable && (
                    <select
                      className="input py-1.5 text-xs"
                      value={measure.variable ?? ''}
                      onChange={(event) =>
                        setMeasures(
                          measures.map((m, i) =>
                            i === index
                              ? {
                                  ...m,
                                  variable: event.target.value,
                                  alias: `${m.agg}_${event.target.value}`,
                                }
                              : m,
                          ),
                        )
                      }
                    >
                      {numeric.map((v) => (
                        <option key={v.name} value={v.name}>
                          {optionLabel(v)}
                        </option>
                      ))}
                    </select>
                  )}
                  <select
                    className="input py-1.5 text-xs"
                    value={measure.weight ?? ''}
                    onChange={(event) =>
                      setMeasures(
                        measures.map((m, i) =>
                          i === index ? { ...m, weight: event.target.value || null } : m,
                        ),
                      )
                    }
                  >
                    <option value="">Unweighted</option>
                    {numeric.map((v) => (
                      <option key={v.name} value={v.name}>
                        Weight by {v.name}
                      </option>
                    ))}
                  </select>
                </div>
              )
            })}
            <button
              className="btn-secondary btn-sm w-full"
              onClick={() => setMeasures([...measures, { agg: 'count', alias: `count_${measures.length}` }])}
            >
              + Add measure
            </button>
            </>
          )}
        </Card>

        <Card title="Filters">
          <FilterBuilder variables={allVariables} value={filters} onChange={setFilters} />
        </Card>

        <Card title="Display">
          <Field
            label="Chart type"
            hint={
              chartType === 'population_pyramid'
                ? 'Group by an age band and then by sex: the bands become the axis, the two sexes the two sides.'
                : isBox
                  ? 'Group by the thing to compare across - province, interviewer, month - and each one gets a box.'
                  : undefined
            }
          >
            <select
              className="input py-1.5 text-xs"
              value={chartType}
              onChange={(event) => setChartType(event.target.value as ChartType)}
            >
              {CHART_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Order">
            <select
              className="input py-1.5 text-xs"
              value={display.sort ?? 'none'}
              onChange={(event) =>
                setDisplay({ ...display, sort: event.target.value as BuildOptions['sort'] })
              }
            >
              <option value="value_desc">Largest first</option>
              <option value="value_asc">Smallest first</option>
              <option value="label_asc">By name (A-Z)</option>
              <option value="label_desc">By name (Z-A)</option>
              <option value="none">As the query returned them</option>
            </select>
          </Field>

          <Field
            label="Show only the top"
            hint={
              isBox
                ? 'The rest are left off. Boxes cannot be added together, so there is no "Other" box to put them in.'
                : "The rest are added together into one 'Other'. Blank keeps them all."
            }
          >
            <input
              className="input py-1.5 text-xs"
              type="number"
              min={1}
              max={50}
              value={display.topN ?? ''}
              placeholder="all"
              onChange={(event) =>
                setDisplay({ ...display, topN: Number(event.target.value) || undefined })
              }
            />
          </Field>

          <Field label="Value axis title" hint="Blank uses the measure's own name.">
            <input
              className="input py-1.5 text-xs"
              value={display.valueTitle ?? ''}
              onChange={(event) => setDisplay({ ...display, valueTitle: event.target.value })}
            />
          </Field>

          <div className="grid grid-cols-2 gap-2">
            <Field label="Axis from">
              <input
                className="input py-1.5 text-xs"
                type="number"
                placeholder="auto"
                value={display.valueMin ?? ''}
                onChange={(event) =>
                  setDisplay({
                    ...display,
                    valueMin: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
              />
            </Field>
            <Field label="to">
              <input
                className="input py-1.5 text-xs"
                type="number"
                placeholder="auto"
                value={display.valueMax ?? ''}
                onChange={(event) =>
                  setDisplay({
                    ...display,
                    valueMax: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
              />
            </Field>
          </div>

          <Field label="Target line" hint="A dashed rule across the plot, e.g. the target.">
            <div className="grid grid-cols-2 gap-2">
              <input
                className="input py-1.5 text-xs"
                type="number"
                placeholder="value"
                value={display.referenceValue ?? ''}
                onChange={(event) =>
                  setDisplay({
                    ...display,
                    referenceValue: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
              />
              <input
                className="input py-1.5 text-xs"
                placeholder="label"
                value={display.referenceLabel ?? ''}
                onChange={(event) => setDisplay({ ...display, referenceLabel: event.target.value })}
              />
            </div>
          </Field>

          <div className="mb-3 space-y-1.5 text-xs text-ink-700">
            {/* Offered on every chart type. It used to be withheld from lines,
                areas and scatters because a number on each of a hundred points
                is unreadable - but on a twelve-month series it is exactly what
                a printed report needs, and the count guard below already drops
                the labels when there are too many marks to read. */}
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={Boolean(display.showValues)}
                onChange={(event) =>
                  setDisplay({ ...display, showValues: event.target.checked })
                }
              />
              Print the numbers on the chart
              <span className="text-ink-400">(up to 24 marks)</span>
            </label>
            {(chartType === 'stacked_bar' || chartType === 'area') && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={Boolean(display.percentStack)}
                  onChange={(event) =>
                    setDisplay({ ...display, percentStack: event.target.checked })
                  }
                />
                Stack to 100% (composition, not size)
              </label>
            )}
            {(chartType === 'line' || chartType === 'area') && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={Boolean(display.smooth)}
                  onChange={(event) => setDisplay({ ...display, smooth: event.target.checked })}
                />
                Smooth the line
              </label>
            )}
          </div>

          <Field label="Row limit">
            <input
              className="input py-1.5 text-xs"
              type="number"
              min={1}
              max={10000}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value) || 50)}
            />
          </Field>
          <button className="btn-primary w-full" onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending && <Spinner className="h-4 w-4 text-white" />}
            Run query
          </button>
        </Card>
      </div>

      <div className="space-y-4">
        {!result && suggestions.data && suggestions.data.length > 0 && (
          <Card title="Suggested analyses" subtitle="Built from this dataset's own variables">
            <div className="flex flex-wrap gap-2">
              {suggestions.data.map((suggestion, index) => (
                <button
                  key={index}
                  className="btn-secondary btn-sm"
                  onClick={() => {
                    setDimensions(suggestion.spec.dimensions ?? [])
                    setMeasures(suggestion.spec.measures ?? [{ agg: 'count' }])
                    setChartType(suggestion.chart_type)
                    setTimeout(() => run.mutate(), 0)
                  }}
                >
                  {suggestion.title}
                </button>
              ))}
            </div>
          </Card>
        )}

        <Card
          title="Result"
          subtitle={
            result
              ? `${formatNumber(result.row_count)} rows in ${result.duration_ms} ms`
              : 'Configure a query and run it'
          }
          actions={
            result && (
              <>
                <button className="btn-ghost btn-sm" onClick={() => setShowSql(!showSql)}>
                  {showSql ? 'Hide' : 'Show'} SQL
                </button>
                <button
                  className="btn-secondary btn-sm"
                  onClick={() =>
                    downloadFile(
                      '/analytics/query/export?format=csv',
                      { dataset_id: datasetId, spec },
                      'results.csv',
                    )
                  }
                >
                  CSV
                </button>
                <button
                  className="btn-secondary btn-sm"
                  onClick={() =>
                    downloadFile(
                      '/analytics/query/export?format=xlsx',
                      { dataset_id: datasetId, spec },
                      'results.xlsx',
                    )
                  }
                >
                  Excel
                </button>
                {canSave && (
                  <button className="btn-primary btn-sm" onClick={() => setSaveOpen(true)}>
                    {editing ? 'Save changes' : 'Save as chart'}
                  </button>
                )}
              </>
            )
          }
        >
          {run.isPending ? (
            <Loading label="Running query" />
          ) : run.error ? (
            <ErrorNote error={run.error} />
          ) : !result ? (
            <EmptyState
              icon="◱"
              title="Nothing to show yet"
              description="Pick a grouping and a measure, then run the query."
            />
          ) : (
            <>
              {result.truncated && (
                <p className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Showing the first {formatNumber(result.row_count)} rows. Raise the row limit to
                  see more.
                </p>
              )}
              <ChartCard result={result} chartType={chartType} height={420} display={display} />
              {showSql && (
                <pre className="mt-4 overflow-x-auto rounded-card bg-ink-900 p-3 text-xs text-ink-100">
                  {result.sql}
                </pre>
              )}
            </>
          )}
        </Card>
      </div>

      <SaveChartModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        datasetId={datasetId}
        datasetName={datasetName}
        chartType={chartType}
        display={display}
        spec={spec}
        editing={editing}
        onSaved={onSaved}
      />
    </div>
  )
}

function SaveChartModal({
  open,
  onClose,
  datasetId,
  datasetName,
  chartType,
  display,
  spec,
  editing,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  datasetId: string
  datasetName: string
  chartType: ChartType
  /** How it is drawn, saved with it so a dashboard shows the same chart. */
  display: BuildOptions
  spec: QuerySpec
  /** The chart this was opened from, which is updated rather than duplicated. */
  editing?: Chart
  onSaved: () => void
}) {
  const toast = useToast()
  const [name, setName] = useState(editing?.name ?? '')
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name || editing?.name || `Chart on ${datasetName}`,
        dataset_id: datasetId,
        chart_type: chartType,
        spec: { query: spec, options: display },
      }
      return editing
        ? api.patch(`/dashboards/charts/${editing.id}`, body)
        : api.post('/dashboards/charts', body)
    },
    onSuccess: () => {
      onSaved()
      if (!editing) setName('')
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? `Save changes to "${editing.name}"` : 'Save as chart'}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            {editing ? 'Save changes' : 'Save chart'}
          </button>
        </>
      }
    >
      <Field label="Chart name" hint="Saved charts can be added to any dashboard.">
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={`Chart on ${datasetName}`}
        />
      </Field>
    </Modal>
  )
}

function CrosstabBuilder({
  datasetId,
  datasetName,
  groupable,
  numeric,
  allVariables,
  canSave,
  editing,
}: {
  datasetId: string
  datasetName: string
  groupable: NonNullable<VariableList>
  numeric: NonNullable<VariableList>
  allVariables: NonNullable<VariableList>
  canSave: boolean
  /** The saved cross-tabulation being edited, if this was opened from one. */
  editing?: Chart
}) {
  const toast = useToast()
  const [rowVariable, setRowVariable] = useState(groupable[0]?.name ?? '')
  const [columnVariable, setColumnVariable] = useState(groupable[1]?.name ?? '')
  const [percentages, setPercentages] = useState<'none' | 'row' | 'column' | 'total'>('none')
  const [measure, setMeasure] = useState<Measure>({ agg: 'count' })
  const [filters, setFilters] = useState<FilterGroup>(emptyFilter())
  const [result, setResult] = useState<CrosstabResult | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)

  useEffect(() => {
    setRowVariable(groupable[0]?.name ?? '')
    setColumnVariable(groupable[1]?.name ?? '')
    setResult(null)
  }, [datasetId, groupable])

  // A saved cross-tabulation opened for editing keeps the request it was made
  // from, so this is filling the form back in from it.
  useEffect(() => {
    const saved = editing?.spec?.crosstab as CrosstabRequest | undefined
    if (!saved) return
    setRowVariable(saved.row_variable)
    setColumnVariable(saved.column_variable)
    setPercentages(saved.percentages ?? 'none')
    setMeasure(saved.measure ?? { agg: 'count' })
    setFilters(saved.filters ?? emptyFilter())
  }, [editing])

  const body: CrosstabRequest = {
    row_variable: rowVariable,
    column_variable: columnVariable,
    measure,
    filters,
    percentages,
    include_totals: true,
    use_labels: true,
  }

  const run = useMutation({
    mutationFn: () => api.post<CrosstabResult>(`/analytics/datasets/${datasetId}/crosstab`, body),
    onSuccess: setResult,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })


  return (
    <div className="mt-4 grid gap-6 lg:grid-cols-[330px_1fr]">
      <div className="space-y-4">
        <Card title="Table setup">
          <Field
            label="Rows"
            hint="Leave one of the two empty to tabulate a single variable on its own."
          >
            <select
              className="input py-1.5 text-xs"
              value={rowVariable}
              onChange={(event) => setRowVariable(event.target.value)}
            >
              <option value="">No rows</option>
              {groupable.map((v) => (
                <option key={v.name} value={v.name}>
                  {optionLabel(v)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Columns">
            <select
              className="input py-1.5 text-xs"
              value={columnVariable}
              onChange={(event) => setColumnVariable(event.target.value)}
            >
              <option value="">No columns</option>
              {groupable.map((v) => (
                <option key={v.name} value={v.name}>
                  {optionLabel(v)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Cell values">
            <select
              className="input py-1.5 text-xs"
              value={measure.agg}
              onChange={(event) => {
                const agg = event.target.value as Aggregation
                const needs = AGGREGATIONS.find((a) => a.value === agg)?.needsVariable
                setMeasure({ agg, variable: needs ? numeric[0]?.name : null })
              }}
            >
              {AGGREGATIONS.filter((a) => a.value !== 'share').map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </Field>
          {AGGREGATIONS.find((a) => a.value === measure.agg)?.needsVariable && (
            <Field label="Of variable">
              <select
                className="input py-1.5 text-xs"
                value={measure.variable ?? ''}
                onChange={(event) => setMeasure({ ...measure, variable: event.target.value })}
              >
                {numeric.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Percentages">
            <select
              className="input py-1.5 text-xs"
              value={percentages}
              onChange={(event) => setPercentages(event.target.value as typeof percentages)}
            >
              <option value="none">Counts only</option>
              <option value="row">Row percentages</option>
              <option value="column">Column percentages</option>
              <option value="total">Percent of total</option>
            </select>
          </Field>
        </Card>

        <Card title="Filters">
          <FilterBuilder variables={allVariables} value={filters} onChange={setFilters} />
        </Card>

        <button
          className="btn-primary w-full"
          onClick={() => run.mutate()}
          disabled={run.isPending || (!rowVariable && !columnVariable)}
        >
          {run.isPending && <Spinner className="h-4 w-4 text-white" />}
          Build table
        </button>
      </div>

      <Card
        title={`Cross-tabulation: ${datasetName}`}
        actions={
          result && (
            <>
              <button
                className="btn-secondary btn-sm"
                onClick={() =>
                  downloadFile(
                    `/analytics/datasets/${datasetId}/crosstab/export`,
                    body,
                    'crosstab.csv',
                  )
                }
              >
                Export CSV
              </button>
              {canSave && (
                <button className="btn-primary btn-sm" onClick={() => setSaveOpen(true)}>
                  {editing ? 'Save changes' : 'Save for dashboards'}
                </button>
              )}
            </>
          )
        }
      >
        {run.isPending ? (
          <Loading />
        ) : run.error ? (
          <ErrorNote error={run.error} />
        ) : !result ? (
          <EmptyState
            icon="▦"
            title="No table yet"
            description="Choose a row and a column variable, then build the table."
          />
        ) : (
          <>
            <CrosstabTable result={result} />

            <div className="mt-5">
              <ChartCard
                showToggle={false}
                chartType="stacked_bar"
                height={340}
                result={{
                  columns: [
                    {
                      name: 'row',
                      label: result.row_variable,
                      type: 'dimension',
                      data_type: 'text',
                    },
                    {
                      name: 'col',
                      label: result.column_variable,
                      type: 'dimension',
                      data_type: 'text',
                    },
                    { name: 'value', label: 'Value', type: 'measure', data_type: 'number' },
                  ],
                  rows: result.row_labels.flatMap((rowLabel, rowIndex) =>
                    result.column_labels.map((columnLabel, columnIndex) => [
                      rowLabel,
                      columnLabel,
                      result.values[rowIndex][columnIndex],
                    ]),
                  ),
                  row_count: result.row_labels.length * result.column_labels.length,
                  truncated: false,
                  sql: '',
                  duration_ms: 0,
                }}
              />
            </div>
          </>
        )}
      </Card>

      <SaveCrosstabModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        datasetId={datasetId}
        datasetName={datasetName}
        request={body}
        editing={editing}
      />
    </div>
  )
}

function SaveCrosstabModal({
  open,
  onClose,
  datasetId,
  datasetName,
  request,
  editing,
}: {
  open: boolean
  onClose: () => void
  datasetId: string
  datasetName: string
  request: CrosstabRequest
  /** The saved cross-tabulation being edited, updated rather than duplicated. */
  editing?: Chart
}) {
  const toast = useToast()
  const [name, setName] = useState(editing?.name ?? '')

  // A one-way table is "region", not "region by " with nothing after it.
  const defaultName =
    request.row_variable && request.column_variable
      ? `${request.row_variable} by ${request.column_variable}`
      : request.row_variable || request.column_variable

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name || editing?.name || defaultName,
        dataset_id: datasetId,
        chart_type: 'crosstab',
        // A crosstab spec holds the request rather than a query, and the server
        // branches on that when rendering.
        spec: { crosstab: request },
      }
      return editing
        ? api.patch(`/dashboards/charts/${editing.id}`, body)
        : api.post('/dashboards/charts', body)
    },
    onSuccess: () => {
      toast.push(
        editing ? 'Cross-tabulation updated' : 'Cross-tabulation saved; add it to a dashboard',
        'success',
      )
      if (!editing) setName('')
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Save cross-tabulation"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            Save
          </button>
        </>
      }
    >
      <Field
        label="Name"
        hint={`Saved against ${datasetName}. It appears alongside charts when adding a dashboard widget.`}
      >
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={defaultName}
        />
      </Field>
    </Modal>
  )
}

const MULTISELECT_CHARTS: { value: ChartType; label: string }[] = [
  { value: 'horizontal_bar', label: 'Horizontal bar' },
  { value: 'bar', label: 'Vertical bar' },
  { value: 'donut', label: 'Donut' },
  { value: 'pie', label: 'Pie' },
  { value: 'table', label: 'Table' },
]

/**
 * A "tick all that apply" question, charted from the columns it arrived as.
 *
 * The question is not in the file: toilet__1, toilet__2 and toilet__3 are, each
 * holding 1 where that option was ticked. Tabulating any one of them answers
 * "how many chose flush", never "what do people use". This puts the set back
 * together - one bar per option, counted down its own column - and the shares
 * add to more than 100, because more than one may be ticked.
 */
function MultiSelectBuilder({
  datasetId,
  datasetName,
  allVariables,
  canSave,
  editing,
}: {
  datasetId: string
  datasetName: string
  allVariables: NonNullable<VariableList>
  canSave: boolean
  /** The saved chart being edited, if this was opened from one. */
  editing?: Chart
}) {
  const toast = useToast()
  const [columns, setColumns] = useState<string[]>([])
  const [percentOf, setPercentOf] = useState<MultiSelectRequest['percent_of']>('respondents')
  const [sort, setSort] = useState<MultiSelectRequest['sort']>('value_desc')
  const [show, setShow] = useState<MultiSelectRequest['show']>('count')
  const [chartType, setChartType] = useState<ChartType>('horizontal_bar')
  const [display, setDisplay] = useState<BuildOptions>({ sort: 'none' })
  const [filters, setFilters] = useState<FilterGroup>(emptyFilter())
  const [result, setResult] = useState<QueryResult | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [search, setSearch] = useState('')
  /** Open while the options are being named. */
  const [naming, setNaming] = useState(false)
  /** Set when a saved chart has just been loaded and wants running. */
  const [pending, setPending] = useState(false)

  // Which sets of columns in this file look like one question. Offered rather
  // than guessed at: picking the question by name beats ticking twelve columns.
  const groups = useQuery({
    queryKey: ['multiselect-groups', datasetId],
    queryFn: () =>
      api.get<MultiSelectGroup[]>(`/analytics/datasets/${datasetId}/multiselect-groups`),
    enabled: Boolean(datasetId),
  })

  useEffect(() => {
    setColumns([])
    setResult(null)
  }, [datasetId])

  useEffect(() => {
    const saved = editing?.spec?.multiselect
    if (!saved) return
    setColumns(saved.columns ?? [])
    setPercentOf(saved.percent_of ?? 'respondents')
    setSort(saved.sort ?? 'value_desc')
    setShow(saved.show ?? 'count')
    setFilters(saved.filters ?? emptyFilter())
    setChartType(editing?.chart_type as ChartType)
    setDisplay((editing?.spec?.options as BuildOptions) ?? { sort: 'none' })
    setPending(true)
  }, [editing])

  const body: MultiSelectRequest = {
    columns,
    filters,
    percent_of: percentOf,
    sort,
    show,
  }

  const run = useMutation({
    mutationFn: () =>
      api.post<QueryResult>(`/analytics/datasets/${datasetId}/multiselect`, body),
    onSuccess: setResult,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  // Run once the loaded columns have reached the state the request is built
  // from, rather than from inside the effect that fills them in.
  useEffect(() => {
    if (!pending || !columns.length) return
    setPending(false)
    run.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, columns])

  // Which question the ticked columns belong to, so its options can be shown
  // as a list to include or leave out.
  const group = useMemo(
    () => groups.data?.find((entry) => entry.columns.some((name) => columns.includes(name))),
    [groups.data, columns],
  )

  const others = useMemo(() => {
    const inGroup = new Set(group?.columns ?? [])
    const needle = search.trim().toLowerCase()
    return allVariables.filter(
      (variable) =>
        !inGroup.has(variable.name) &&
        (needle
          ? `${variable.name} ${variable.label ?? ''}`.toLowerCase().includes(needle)
          : columns.includes(variable.name)),
    )
  }, [allVariables, group, columns, search])

  const toggle = (name: string) =>
    setColumns(
      columns.includes(name) ? columns.filter((entry) => entry !== name) : [...columns, name],
    )

  return (
    <div className="mt-4 grid gap-6 lg:grid-cols-[330px_1fr]">
      <div className="space-y-4">
        <Card title="The question">
          {groups.isLoading ? (
            <Loading />
          ) : (
            <>
              <Field
                label="Multiple-select question"
                hint={
                  groups.data?.length
                    ? 'Found from the column names: toilet__1, toilet__2 and so on are one question.'
                    : 'No sets of option columns were found in this dataset. Tick the 0/1 columns yourself below.'
                }
              >
                <select
                  className="input py-1.5 text-xs"
                  value={group?.stem ?? ''}
                  onChange={(event) => {
                    const chosen = groups.data?.find((entry) => entry.stem === event.target.value)
                    setColumns(chosen ? chosen.columns : [])
                    setResult(null)
                  }}
                >
                  <option value="">Choose the columns myself</option>
                  {groups.data?.map((entry) => (
                    <option key={entry.stem} value={entry.stem}>
                      {entry.label === entry.stem
                        ? `${entry.stem} (${entry.columns.length} options)`
                        : `${entry.label} - ${entry.stem} (${entry.columns.length} options)`}
                    </option>
                  ))}
                </select>
              </Field>

              {group && (
                <div className="mb-3">
                  <p className="mb-1.5 text-xs font-medium text-ink-700">
                    Options to show
                    <button
                      className="btn-ghost btn-sm ml-2"
                      onClick={() =>
                        setColumns(
                          columns.length === group.columns.length ? [] : [...group.columns],
                        )
                      }
                    >
                      {columns.length === group.columns.length ? 'Clear all' : 'Tick all'}
                    </button>
                  </p>
                  <div className="max-h-56 space-y-1 overflow-y-auto rounded-card border border-ink-200 p-2">
                    {(group.options ?? group.columns.map((column) => ({ column, label: column }))).map(
                      (option) => (
                        <label
                          key={option.column}
                          className="flex items-start gap-2 text-xs text-ink-700"
                        >
                          <input
                            type="checkbox"
                            className="mt-0.5"
                            checked={columns.includes(option.column)}
                            onChange={() => toggle(option.column)}
                          />
                          <span>
                            {/* The name the bar will carry, which is what
                                somebody ticking eight boxes out of nineteen is
                                choosing between. The column name follows it,
                                and only where it says something the label does
                                not - printed twice it read as a bug. */}
                            {option.label}
                            {option.label !== option.column && (
                              <span className="ml-1 text-ink-400">{option.column}</span>
                            )}
                          </span>
                        </label>
                      ),
                    )}
                  </div>
                  {/* Why the bars are numbered, and what to do about it. The
                      option text is usually in the file and is read from it;
                      an export that carries none leaves nothing to read, and
                      the answer is to write the names once, here, where the
                      question is in front of you. */}
                  {group.unnamed && (
                    <p className="mt-1.5 text-xs text-amber-700">
                      This file gives no names for these options, so they are numbered.
                      {canSave ? (
                        <>
                          {' '}
                          <button
                            className="font-medium underline"
                            onClick={() => setNaming(true)}
                          >
                            Name them
                          </button>{' '}
                          and the names stay with the dataset - every chart, filter and
                          table shows them.
                        </>
                      ) : (
                        ' Ask somebody who can edit this dataset to name them.'
                      )}
                    </p>
                  )}
                  {!group.unnamed && canSave && (
                    <button
                      className="btn-ghost btn-sm mt-1 px-0 text-xs"
                      onClick={() => setNaming(true)}
                    >
                      Rename the options
                    </button>
                  )}
                </div>
              )}

              {!group && (
                <div className="mb-3">
                  <input
                    className="input mb-2 py-1.5 text-xs"
                    placeholder="Search the columns"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                  <div className="max-h-56 space-y-1 overflow-y-auto rounded-card border border-ink-200 p-2">
                    {others.length === 0 && (
                      <p className="p-1 text-xs text-ink-500">
                        Search for the columns that hold this question, then tick them.
                      </p>
                    )}
                    {others.map((variable) => (
                      <label
                        key={variable.name}
                        className="flex items-start gap-2 text-xs text-ink-700"
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={columns.includes(variable.name)}
                          onChange={() => toggle(variable.name)}
                        />
                        <span>
                          {variable.label || variable.name}
                          {variable.label && <span className="ml-1 text-ink-400">{variable.name}</span>}
                        </span>
                      </label>
                    ))}
                  </div>
                  <p className="mt-1 text-xs text-ink-500">
                    {columns.length} column{columns.length === 1 ? '' : 's'} ticked
                  </p>
                </div>
              )}
            </>
          )}
        </Card>

        <Card title="Filters">
          <FilterBuilder variables={allVariables} value={filters} onChange={setFilters} />
        </Card>

        <Card title="Display">
          <Field label="Chart type">
            <select
              className="input py-1.5 text-xs"
              value={chartType}
              onChange={(event) => {
                const next = event.target.value as ChartType
                setChartType(next)
                // A table is the one place both numbers belong together; on a
                // chart they are two scales sharing one axis.
                if (next === 'table' && show !== 'both') setShow('both')
                if (next !== 'table' && show === 'both') setShow('count')
              }}
            >
              {MULTISELECT_CHARTS.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Show">
            <select
              className="input py-1.5 text-xs"
              value={show}
              onChange={(event) => setShow(event.target.value as MultiSelectRequest['show'])}
            >
              <option value="count">How many chose it</option>
              <option value="percent">Percent</option>
              <option value="both">Both (best in a table)</option>
            </select>
          </Field>
          <Field
            label="Percent of"
            hint="Respondents is the usual reading: the shares add to more than 100 because more than one option may be ticked."
          >
            <select
              className="input py-1.5 text-xs"
              value={percentOf}
              onChange={(event) =>
                setPercentOf(event.target.value as MultiSelectRequest['percent_of'])
              }
            >
              <option value="respondents">People who were asked the question</option>
              <option value="rows">Every row in the dataset</option>
            </select>
          </Field>
          <Field label="Order">
            <select
              className="input py-1.5 text-xs"
              value={sort}
              onChange={(event) => setSort(event.target.value as MultiSelectRequest['sort'])}
            >
              <option value="value_desc">Most chosen first</option>
              <option value="value_asc">Least chosen first</option>
              <option value="label_asc">By option name (A-Z)</option>
              <option value="none">In the order the columns come</option>
            </select>
          </Field>
          <label className="mb-3 flex items-center gap-2 text-xs text-ink-700">
            <input
              type="checkbox"
              checked={Boolean(display.showValues)}
              onChange={(event) => setDisplay({ ...display, showValues: event.target.checked })}
            />
            Print the numbers on the chart
          </label>
          <button
            className="btn-primary w-full"
            onClick={() => run.mutate()}
            disabled={run.isPending || !columns.length}
          >
            {run.isPending && <Spinner className="h-4 w-4 text-white" />}
            Count the answers
          </button>
        </Card>
      </div>

      <Card
        title={group?.label || 'Tick all that apply'}
        subtitle={
          result
            ? `${result.row_count} option${result.row_count === 1 ? '' : 's'}, out of ` +
              `${formatNumber(result.total_rows_scanned ?? 0)} ${
                percentOf === 'respondents' ? 'who were asked' : 'rows'
              }`
            : `${columns.length} column${columns.length === 1 ? '' : 's'} chosen`
        }
        actions={
          result &&
          canSave && (
            <button className="btn-primary btn-sm" onClick={() => setSaveOpen(true)}>
              {editing ? 'Save changes' : 'Save as chart'}
            </button>
          )
        }
      >
        {run.isPending ? (
          <Loading label="Counting the options" />
        ) : run.error ? (
          <ErrorNote error={run.error} />
        ) : !result ? (
          <EmptyState
            icon="◱"
            title="Nothing to show yet"
            description="Choose a question, or tick the 0/1 columns it was exported as, then count the answers."
          />
        ) : (
          <ChartCard
            result={result}
            chartType={chartType}
            height={Math.max(320, Math.min(720, result.row_count * 28 + 120))}
            display={display}
          />
        )}
      </Card>

      <SaveMultiSelectModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        datasetId={datasetId}
        datasetName={datasetName}
        chartType={chartType}
        display={display}
        request={body}
        defaultName={group?.label || group?.stem || 'Tick all that apply'}
        editing={editing}
      />

      {naming && group && (
        <NameOptionsModal
          datasetId={datasetId}
          group={group}
          onClose={() => setNaming(false)}
        />
      )}
    </div>
  )
}

/**
 * Naming the options of a multiple-select, all of them at once.
 *
 * The option text is usually in the file - in the question's own value labels,
 * where the number after the underscores is the code - and it is read from
 * there on import. An export that carries none leaves the bars numbered, and
 * naming nineteen columns one at a time through the dataset's own label editor
 * is enough work that nobody does it. This writes the same thing that editor
 * writes: each column's variable label, which every chart, filter and table
 * then shows, and which survives the next export replacing the file.
 */
function NameOptionsModal({
  datasetId,
  group,
  onClose,
}: {
  datasetId: string
  group: MultiSelectGroup
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const options = group.options ?? group.columns.map((column) => ({ column, label: column }))
  // Blank where the name is only a number: that is a placeholder, not a name,
  // and offering it as the text to edit would have people saving "Option 8".
  const [names, setNames] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      options.map((option) => [
        option.column,
        option.label.startsWith('Option ') ? '' : option.label,
      ]),
    ),
  )

  const save = useMutation({
    mutationFn: async () => {
      const changed = options.filter(
        (option) =>
          (names[option.column] ?? '').trim() !==
          (option.label.startsWith('Option ') ? '' : option.label),
      )
      for (const option of changed) {
        await api.patch(
          `/datasets/${datasetId}/variables/${encodeURIComponent(option.column)}`,
          { label: (names[option.column] ?? '').trim() },
        )
      }
      return changed.length
    },
    onSuccess: (changed) => {
      toast.push(
        changed ? `Named ${changed} option${changed === 1 ? '' : 's'}` : 'Nothing changed',
        'success',
      )
      queryClient.invalidateQueries({ queryKey: ['multiselect-groups', datasetId] })
      queryClient.invalidateQueries({ queryKey: ['dataset', datasetId] })
      queryClient.invalidateQueries({ queryKey: ['variables', datasetId] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title={`Name the options of ${group.label || group.stem}`}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Spinner className="h-4 w-4 text-white" />}
            Save the names
          </button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-500">
        These are the words each option is drawn under, here and everywhere else this
        dataset is used. Leave one blank to leave it numbered.
      </p>
      <div className="max-h-96 space-y-1.5 overflow-y-auto pr-1">
        {options.map((option) => (
          <label key={option.column} className="flex items-center gap-2">
            <code className="w-40 shrink-0 truncate text-xs text-ink-500" title={option.column}>
              {option.column}
            </code>
            <input
              className="input py-1.5 text-sm"
              value={names[option.column] ?? ''}
              placeholder={option.label}
              onChange={(event) =>
                setNames({ ...names, [option.column]: event.target.value })
              }
            />
          </label>
        ))}
      </div>
    </Modal>
  )
}

function SaveMultiSelectModal({
  open,
  onClose,
  datasetId,
  datasetName,
  chartType,
  display,
  request,
  defaultName,
  editing,
}: {
  open: boolean
  onClose: () => void
  datasetId: string
  datasetName: string
  chartType: ChartType
  display: BuildOptions
  request: MultiSelectRequest
  defaultName: string
  /** The saved chart being edited, updated rather than duplicated. */
  editing?: Chart
}) {
  const toast = useToast()
  const [name, setName] = useState(editing?.name ?? '')

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name || editing?.name || defaultName,
        dataset_id: datasetId,
        chart_type: chartType,
        // The columns rather than a query: the server puts the question back
        // together when it renders the widget, so a dashboard filter still
        // reaches it.
        spec: { multiselect: request, options: display },
      }
      return editing
        ? api.patch(`/dashboards/charts/${editing.id}`, body)
        : api.post('/dashboards/charts', body)
    },
    onSuccess: () => {
      toast.push(editing ? 'Chart updated' : 'Chart saved; add it to a dashboard', 'success')
      if (!editing) setName('')
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? `Save changes to "${editing.name}"` : 'Save as chart'}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            {editing ? 'Save changes' : 'Save chart'}
          </button>
        </>
      }
    >
      <Field
        label="Chart name"
        hint={`Saved against ${datasetName}. It appears alongside charts when adding a dashboard widget.`}
      >
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={defaultName}
        />
      </Field>
    </Modal>
  )
}
