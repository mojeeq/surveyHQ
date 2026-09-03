import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Dataset, FilterGroup, Page } from '@/lib/types'
import { Field } from './ui'

export interface FilterControl {
  /** The variable every widget that has it will be filtered on. */
  variable: string
  /** Which dataset's values populate the dropdown. */
  dataset_id: string
  label?: string
}

/**
 * The filter bar above a dashboard's widgets.
 *
 * A dashboard's widgets can draw on several datasets, so a control names a
 * variable rather than a dataset: the server applies it to every widget whose
 * dataset carries that variable and leaves the others as they were. That is
 * why a control can be useful even when it only narrows half the page.
 */
export default function DashboardFilters({
  controls,
  value,
  onChange,
}: {
  controls: FilterControl[]
  value: Record<string, string>
  onChange: (next: Record<string, string>) => void
}) {
  if (!controls.length) return null

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-ink-200 bg-white px-4 py-3">
      {controls.map((control) => (
        <FilterControlInput
          key={`${control.dataset_id}:${control.variable}`}
          control={control}
          value={value[control.variable] ?? ''}
          onChange={(next) => onChange({ ...value, [control.variable]: next })}
        />
      ))}
      {Object.values(value).some(Boolean) && (
        <button className="btn-ghost btn-sm mb-1 text-ink-500" onClick={() => onChange({})}>
          Clear
        </button>
      )}
    </div>
  )
}

function FilterControlInput({
  control,
  value,
  onChange,
}: {
  control: FilterControl
  value: string
  onChange: (value: string) => void
}) {
  const values = useQuery({
    queryKey: ['values', control.dataset_id, control.variable],
    queryFn: () =>
      api.get<{ value: string; label: string; count: number }[]>(
        `/datasets/${control.dataset_id}/variables/${encodeURIComponent(control.variable)}/values?limit=200`,
      ),
  })

  return (
    <Field label={control.label || control.variable}>
      <select
        className="input w-48"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">All</option>
        {(values.data ?? []).map((option) => (
          <option key={String(option.value)} value={String(option.value)}>
            {option.label || String(option.value)}
          </option>
        ))}
      </select>
    </Field>
  )
}

/** Turn the bar's selections into the filter the render endpoint expects. */
export function toFilterGroup(
  controls: FilterControl[],
  value: Record<string, string>,
): FilterGroup {
  return {
    op: 'and',
    conditions: controls
      .filter((control) => value[control.variable])
      .map((control) => ({
        variable: control.variable,
        operator: 'eq',
        // Compare against the label shown in the dropdown, since that is what
        // the values endpoint returns and what the user picked.
        value: value[control.variable],
        use_label: true,
      })),
    groups: [],
  }
}

/** Variables worth offering as a filter: few enough values to pick from. */
export function filterableVariables(dataset: Dataset | undefined) {
  return (dataset?.variables ?? []).filter(
    (v) => !v.is_hidden && v.var_type === 'categorical' && v.n_unique <= 200,
  )
}

export function useDashboardDatasets(ids: string[]) {
  return useQuery({
    queryKey: ['datasets', 'for-filters'],
    queryFn: () => api.get<Page<Dataset>>('/datasets?limit=200&status=ready'),
    select: (page) => page.items.filter((d) => ids.includes(d.id)),
    enabled: ids.length > 0,
  })
}
