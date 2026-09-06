import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Dataset, FilterGroup, Page } from '@/lib/types'

export interface FilterControl {
  /** The variable every widget that has it will be filtered on. */
  variable: string
  /** Which dataset's values populate the dropdown. */
  dataset_id: string
  label?: string
  /**
   * Which page of the dashboard offers this control. Pages ask different
   * questions, so they get different filters. Absent on controls saved before
   * filters were per page; those belong to the first page.
   */
  page?: number
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
  background,
  onChange,
}: {
  controls: FilterControl[]
  value: Record<string, string>
  /** The bar's own colour, set in Appearance. Empty means plain white. */
  background?: string
  onChange: (next: Record<string, string>) => void
}) {
  if (!controls.length) return null

  // A filter bar is chrome, not content: it should cost the dashboard as
  // little vertical room as it can and still be operable. Label and control
  // sit on one line rather than stacked, which halves the height, and the
  // whole row wraps when there are more filters than fit.
  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-ink-200 px-3 py-2"
      style={{ backgroundColor: background || '#ffffff' }}
    >
      {controls.map((control) => (
        <FilterControlInput
          key={controlKey(control)}
          control={control}
          value={value[control.variable] ?? ''}
          onChange={(next) => onChange({ ...value, [control.variable]: next })}
        />
      ))}
      {Object.values(value).some(Boolean) && (
        <button className="btn-ghost btn-sm text-ink-500" onClick={() => onChange({})}>
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

  const name = control.label || control.variable
  return (
    <label className="flex items-center gap-1.5 text-xs text-ink-600">
      <span className="whitespace-nowrap font-medium">{name}</span>
      <select
        className="input h-7 w-40 py-0 text-xs"
        aria-label={name}
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
    </label>
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

/** The controls belonging to one page. A control saved before filters were
 *  per page has no page of its own and stays on the first one. */
export function controlsForPage(controls: FilterControl[], page: number): FilterControl[] {
  return controls.filter((control) => (control.page ?? 0) === page)
}

/**
 * What makes one control the same as another.
 *
 * The variable name alone is not enough. A Survey Solutions export puts
 * interview__key in every level it produces, so a dashboard drawing on the
 * interview level and a roster has two different controls with one name -
 * and identifying them by name alone made ticking one tick both.
 */
export function controlKey(control: { dataset_id: string; variable: string }): string {
  return `${control.dataset_id}::${control.variable}`
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
