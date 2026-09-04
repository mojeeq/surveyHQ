import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, downloadFile } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber } from '@/lib/format'
import type {
  Aggregation,
  ChartType,
  CrosstabRequest,
  CrosstabResult,
  Dataset,
  DateGrain,
  Dimension,
  FilterGroup,
  Measure,
  Page,
  Project,
  QueryResult,
  QuerySpec,
  Variable,
} from '@/lib/types'
import ChartCard from '@/components/ChartCard'
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
  const named = v.label ? `${v.name} — ${v.label}` : v.name
  return v.n_unique > 200 ? `${named} (${formatNumber(v.n_unique)} values)` : named
}

export default function Explore() {
  const [params, setParams] = useSearchParams()
  const toast = useToast()
  const { can } = useAuth()
  const [mode, setMode] = useState<'aggregate' | 'crosstab'>('aggregate')

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

  const requested = params.get('dataset') ?? ''
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
        title="Explore"
        description="Build tabulations and charts against any dataset."
        actions={
          <div className="flex flex-wrap items-center gap-2">
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
        ]}
        active={mode}
        onChange={(id) => setMode(id as 'aggregate' | 'crosstab')}
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
          datasetId={datasetId}
          datasetName={dataset.data.name}
          groupable={groupable}
          numeric={numeric}
          allVariables={variables}
          canSave={can('analyst')}
          onSaved={() => toast.push('Chart saved', 'success')}
        />
      ) : (
        <CrosstabBuilder
          datasetId={datasetId}
          datasetName={dataset.data.name}
          groupable={groupable}
          numeric={numeric}
          allVariables={variables}
          canSave={can('analyst')}
        />
      )}
    </>
  )
}

type VariableList = Dataset['variables']

function AggregateBuilder({
  datasetId,
  datasetName,
  groupable,
  numeric,
  allVariables,
  canSave,
  onSaved,
}: {
  datasetId: string
  datasetName: string
  groupable: NonNullable<VariableList>
  numeric: NonNullable<VariableList>
  allVariables: NonNullable<VariableList>
  canSave: boolean
  onSaved: () => void
}) {
  const toast = useToast()
  const [dimensions, setDimensions] = useState<Dimension[]>([])
  const [measures, setMeasures] = useState<Measure[]>([{ agg: 'count', alias: 'count' }])
  const [filters, setFilters] = useState<FilterGroup>(emptyFilter())
  const [chartType, setChartType] = useState<ChartType>('bar')
  const [display, setDisplay] = useState<BuildOptions>({ sort: 'value_desc' })
  const [limit, setLimit] = useState(50)
  const [result, setResult] = useState<QueryResult | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [showSql, setShowSql] = useState(false)

  // Reset the builder whenever the dataset changes; variable names differ.
  useEffect(() => {
    setDimensions([])
    setMeasures([{ agg: 'count', alias: 'count' }])
    setFilters(emptyFilter())
    setResult(null)
  }, [datasetId])

  const spec: QuerySpec = {
    dimensions,
    measures,
    filters,
    sort: measures.length
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

        <Card title="Measure">
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
              <option value="label_asc">By name (A–Z)</option>
              <option value="label_desc">By name (Z–A)</option>
              <option value="none">As the query returned them</option>
            </select>
          </Field>

          <Field
            label="Show only the top"
            hint="The rest are added together into one 'Other'. Blank keeps them all."
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
            {/* Numbers on the marks read on bars and slices; on a line they
                collide with each other, so that combination is not offered. */}
            {chartType !== 'line' && chartType !== 'area' && chartType !== 'scatter' && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={Boolean(display.showValues)}
                  onChange={(event) =>
                    setDisplay({ ...display, showValues: event.target.checked })
                  }
                />
                Print the numbers on the chart
                <span className="text-ink-400">(up to 24 bars)</span>
              </label>
            )}
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
                    Save as chart
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
  onSaved: () => void
}) {
  const toast = useToast()
  const [name, setName] = useState('')
  const save = useMutation({
    mutationFn: () =>
      api.post('/dashboards/charts', {
        name: name || `Chart on ${datasetName}`,
        dataset_id: datasetId,
        chart_type: chartType,
        spec: { query: spec, options: display },
      }),
    onSuccess: () => {
      onSaved()
      setName('')
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Save as chart"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            Save chart
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
}: {
  datasetId: string
  datasetName: string
  groupable: NonNullable<VariableList>
  numeric: NonNullable<VariableList>
  allVariables: NonNullable<VariableList>
  canSave: boolean
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
          <Field label="Rows">
            <select
              className="input py-1.5 text-xs"
              value={rowVariable}
              onChange={(event) => setRowVariable(event.target.value)}
            >
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
          disabled={run.isPending || !rowVariable || !columnVariable}
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
                  Save for dashboards
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
}: {
  open: boolean
  onClose: () => void
  datasetId: string
  datasetName: string
  request: CrosstabRequest
}) {
  const toast = useToast()
  const [name, setName] = useState('')

  const save = useMutation({
    mutationFn: () =>
      api.post('/dashboards/charts', {
        name: name || `${request.row_variable} by ${request.column_variable}`,
        dataset_id: datasetId,
        chart_type: 'crosstab',
        // A crosstab spec holds the request rather than a query, and the server
        // branches on that when rendering.
        spec: { crosstab: request },
      }),
    onSuccess: () => {
      toast.push('Cross-tabulation saved; add it to a dashboard', 'success')
      setName('')
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
          placeholder={`${request.row_variable} by ${request.column_variable}`}
        />
      </Field>
    </Modal>
  )
}
