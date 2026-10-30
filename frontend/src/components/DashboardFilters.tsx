import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  choiceOf,
  dateConditions,
  dayOf,
  DATE_PREFIX,
  DATE_PRESETS,
  iso,
  isPreset,
  rangeParts,
  rangeValue,
} from '@/lib/date-range'
import type { Condition, Dataset, FilterGroup } from '@/lib/types'

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
  /** A dropdown of the variable's values, or a range of days for a date.
   *  Absent on every control saved before there were date ranges. */
  kind?: 'values' | 'dates'
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
  labelColor,
  basePath,
  onChange,
}: {
  controls: FilterControl[]
  value: Record<string, string>
  /** The bar's own colour, set in Appearance. Empty means plain white. */
  background?: string
  /** The label text, for a bar the default grey disappears into. */
  labelColor?: string
  /** This dashboard's own path, signed in or shared. */
  basePath: string
  onChange: (next: Record<string, string>) => void
}) {
  if (!controls.length) return null

  // A filter bar is chrome, not content: label and control sit on one line
  // rather than stacked, and the whole row wraps when there are more filters
  // than fit. It is drawn at the size of the board's other controls, though.
  // Squeezed to the small one - 12px labels, 28px dropdowns in a tight strip -
  // it read as an afterthought under the tabs, and it is the thing a reader
  // reaches for first.
  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2.5 rounded-card border border-ink-200 px-4 py-2.5"
      style={{ backgroundColor: background || '#ffffff' }}
    >
      {controls.map((control) =>
        control.kind === 'dates' ? (
          <DateRangeInput
            key={controlKey(control)}
            control={control}
            labelColor={labelColor}
            value={value[control.variable] ?? ''}
            onChange={(next) => onChange({ ...value, [control.variable]: next })}
          />
        ) : (
          <FilterControlInput
            key={controlKey(control)}
            control={control}
            basePath={basePath}
            labelColor={labelColor}
            value={value[control.variable] ?? ''}
            onChange={(next) => onChange({ ...value, [control.variable]: next })}
          />
        ),
      )}
      {Object.values(value).some(Boolean) && (
        <button
          className="btn-ghost btn-sm text-ink-500"
          style={labelColor ? { color: labelColor } : undefined}
          onClick={() => onChange({})}
        >
          Clear
        </button>
      )}
    </div>
  )
}

function FilterControlInput({
  control,
  basePath,
  labelColor,
  value,
  onChange,
}: {
  control: FilterControl
  basePath: string
  labelColor?: string
  value: string
  onChange: (value: string) => void
}) {
  // Asked of the dashboard, not of the dataset. The dataset endpoint needs an
  // account and the reader of a shared link has none, so a copied link came up
  // with empty dropdowns for anybody who was not already signed in to that
  // browser - which is why it looked intermittent. The dashboard answers for
  // its own controls, and only for those.
  const values = useQuery({
    queryKey: ['filter-values', basePath, control.variable],
    queryFn: () =>
      api.get<{ value: string; label: string; count: number }[]>(
        `${basePath}/filter-values/${encodeURIComponent(control.variable)}?limit=200`,
      ),
  })

  const name = control.label || control.variable
  return (
    <label className="flex items-center gap-2 text-[13px] text-ink-600">
      <span
        className="whitespace-nowrap font-medium"
        // The label only. The dropdown beside it keeps its own ink, because it
        // is a white control whatever colour the bar behind it is.
        style={labelColor ? { color: labelColor } : undefined}
      >
        {name}
      </span>
      <select
        className="input w-48"
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

/**
 * A date variable's control: a named range, or two days of the reader's own.
 *
 * One select rather than a calendar, because the ranges a fieldwork board is
 * read by are a handful - today, this week - and the two date boxes appear
 * only for the occasional range that is none of them.
 */
function DateRangeInput({
  control,
  labelColor,
  value,
  onChange,
}: {
  control: FilterControl
  labelColor?: string
  value: string
  onChange: (value: string) => void
}) {
  const name = control.label || control.variable
  const custom = Boolean(value) && !isPreset(value)
  const { from, to } = rangeParts(value)
  return (
    <div className="flex flex-wrap items-center gap-2 text-[13px] text-ink-600">
      <span
        className="whitespace-nowrap font-medium"
        style={labelColor ? { color: labelColor } : undefined}
      >
        {name}
      </span>
      <select
        className="input w-48"
        aria-label={name}
        value={custom ? 'custom' : choiceOf(value)}
        onChange={(event) => {
          const next = event.target.value
          // Choosing your own range opens the two boxes on today, so the bar
          // keeps showing something rather than nothing while they are filled.
          if (next === 'custom') {
            const today = iso(dayOf(new Date()))
            onChange(rangeValue(today, today))
          } else {
            onChange(next ? `${DATE_PREFIX}${next}` : '')
          }
        }}
      >
        <option value="">All dates</option>
        {DATE_PRESETS.map((preset) => (
          <option key={preset.value} value={preset.value}>
            {preset.label}
          </option>
        ))}
        <option value="custom">Choose dates…</option>
      </select>
      {custom && (
        <>
          <input
            type="date"
            className="input w-40"
            aria-label={`${name} from`}
            value={from}
            max={to || undefined}
            onChange={(event) => onChange(rangeValue(event.target.value, to))}
          />
          <span>to</span>
          <input
            type="date"
            className="input w-40"
            aria-label={`${name} to`}
            value={to}
            min={from || undefined}
            onChange={(event) => onChange(rangeValue(from, event.target.value))}
          />
        </>
      )}
    </div>
  )
}

/** Turn the bar's selections into the filter the render endpoint expects. */
export function toFilterGroup(
  controls: FilterControl[],
  value: Record<string, string>,
  today: Date = new Date(),
): FilterGroup {
  const conditions: Condition[] = []
  for (const control of controls) {
    const chosen = value[control.variable]
    if (!chosen) continue
    if (control.kind === 'dates') {
      // Worked out here, in the reader's browser, so "today" is their today.
      conditions.push(...dateConditions(control.variable, chosen, dayOf(today)))
    } else {
      conditions.push({
        variable: control.variable,
        operator: 'eq',
        // Compare against the label shown in the dropdown, since that is what
        // the values endpoint returns and what the user picked.
        value: chosen,
        use_label: true,
      })
    }
  }
  return { op: 'and', conditions, groups: [] }
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

/**
 * Variables worth offering as a filter: few enough values to pick from.
 *
 * The cardinality is the question, and asking for the importer's judgement
 * instead was a proxy that stopped holding. A code with no names for its codes
 * - a 1/2/3 region, a 1-to-5 agreement scale - reads as a quantity now rather
 * than as a category, and requiring `categorical` here took every one of them
 * out of the add-filter list on reimport, though three values fit a dropdown
 * as well as they ever did.
 *
 * Dates stay out. Two hundred of them would make a list nobody can use, and a
 * date wants a range rather than a set of ticks.
 */
export function filterableVariables(dataset: Dataset | undefined) {
  return (dataset?.variables ?? []).filter(
    (v) => !v.is_hidden && v.var_type !== 'datetime' && v.n_unique <= 200,
  )
}

/** The variables a date range can be put on: the ones holding dates. */
export function dateVariables(dataset: Dataset | undefined) {
  return (dataset?.variables ?? []).filter((v) => !v.is_hidden && v.var_type === 'datetime')
}

export function useDashboardDatasets(ids: string[]) {
  return useQuery({
    queryKey: ['datasets', 'for-filters'],
    queryFn: () => api.getAll<Dataset>('/datasets?status=ready'),
    select: (page) => page.items.filter((d) => ids.includes(d.id)),
    enabled: ids.length > 0,
  })
}
