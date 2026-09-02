import type { Condition, FilterGroup, FilterOperator, Variable } from '@/lib/types'

const OPERATORS: { value: FilterOperator; label: string; noValue?: boolean }[] = [
  { value: 'eq', label: 'equals' },
  { value: 'ne', label: 'does not equal' },
  { value: 'gt', label: 'greater than' },
  { value: 'gte', label: 'at least' },
  { value: 'lt', label: 'less than' },
  { value: 'lte', label: 'at most' },
  { value: 'in', label: 'is one of' },
  { value: 'not_in', label: 'is not one of' },
  { value: 'contains', label: 'contains' },
  { value: 'starts_with', label: 'starts with' },
  { value: 'between', label: 'between' },
  { value: 'is_null', label: 'is missing', noValue: true },
  { value: 'is_not_null', label: 'is present', noValue: true },
]

export const emptyFilter = (): FilterGroup => ({ op: 'and', conditions: [], groups: [] })

/** Row-per-condition filter editor. Values are sent as-is and bound server side. */
export default function FilterBuilder({
  variables,
  value,
  onChange,
}: {
  variables: Variable[]
  value: FilterGroup
  onChange: (next: FilterGroup) => void
}) {
  const update = (index: number, patch: Partial<Condition>) => {
    const conditions = value.conditions.map((condition, i) =>
      i === index ? { ...condition, ...patch } : condition,
    )
    onChange({ ...value, conditions })
  }

  const add = () => {
    if (!variables.length) return
    onChange({
      ...value,
      conditions: [
        ...value.conditions,
        { variable: variables[0].name, operator: 'eq', value: '', use_label: false },
      ],
    })
  }

  const remove = (index: number) =>
    onChange({ ...value, conditions: value.conditions.filter((_, i) => i !== index) })

  return (
    <div className="space-y-2">
      {value.conditions.length > 1 && (
        <div className="flex items-center gap-2 text-xs text-ink-500">
          Match
          <select
            className="input w-24 py-1 text-xs"
            value={value.op}
            onChange={(event) =>
              onChange({ ...value, op: event.target.value as 'and' | 'or' })
            }
          >
            <option value="and">all</option>
            <option value="or">any</option>
          </select>
          of these conditions
        </div>
      )}

      {value.conditions.map((condition, index) => {
        const operator = OPERATORS.find((o) => o.value === condition.operator)
        const variable = variables.find((v) => v.name === condition.variable)
        const options = variable ? Object.entries(variable.value_labels ?? {}) : []
        return (
          <div key={index} className="flex flex-wrap items-center gap-2">
            <select
              className="input w-44 py-1.5 text-xs"
              value={condition.variable}
              onChange={(event) => update(index, { variable: event.target.value })}
            >
              {variables.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.label ? `${v.name} — ${v.label}` : v.name}
                </option>
              ))}
            </select>

            <select
              className="input w-36 py-1.5 text-xs"
              value={condition.operator}
              onChange={(event) =>
                update(index, { operator: event.target.value as FilterOperator })
              }
            >
              {OPERATORS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>

            {!operator?.noValue &&
              (options.length > 0 && ['eq', 'ne'].includes(condition.operator) ? (
                <select
                  className="input w-40 py-1.5 text-xs"
                  value={String(condition.value ?? '')}
                  onChange={(event) => update(index, { value: event.target.value })}
                >
                  <option value="">Choose…</option>
                  {options.map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="input w-40 py-1.5 text-xs"
                  placeholder={
                    ['in', 'not_in', 'between'].includes(condition.operator)
                      ? 'comma separated'
                      : 'value'
                  }
                  value={
                    Array.isArray(condition.value)
                      ? condition.value.join(', ')
                      : String(condition.value ?? '')
                  }
                  onChange={(event) => {
                    const raw = event.target.value
                    const multi = ['in', 'not_in', 'between'].includes(condition.operator)
                    update(index, {
                      value: multi ? raw.split(',').map((part) => part.trim()) : raw,
                    })
                  }}
                />
              ))}

            <button
              className="btn-ghost btn-sm text-red-600"
              onClick={() => remove(index)}
              aria-label="Remove condition"
            >
              ✕
            </button>
          </div>
        )
      })}

      <button className="btn-secondary btn-sm" onClick={add} disabled={!variables.length}>
        + Add filter
      </button>
    </div>
  )
}
