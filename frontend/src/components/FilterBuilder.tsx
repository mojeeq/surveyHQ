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

/**
 * The operators that mean something between two columns.
 *
 * Kept in step with SQLBuilder.COLUMN_COMPARISONS on the server, which refuses
 * the rest. Offering "is one of" against a whole column would be a question
 * the server then declines to answer, which is a worse way to find out.
 */
export const COLUMN_OPERATORS: FilterOperator[] = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte']

/**
 * The patch that moves a condition between a literal and another column.
 *
 * Its whole job is leaving nothing behind. A row that kept `value` while
 * comparing against a column, or kept `other_variable` after switching back,
 * would send a right hand side it is not using, and the one the server acts on
 * would not be the one on screen.
 *
 * The operator survives only if it still means something: going to a column
 * with "contains" selected would make a row the server refuses, so it falls
 * back to equals.
 */
export function sideSwitch(
  condition: Condition,
  toColumn: boolean,
  variables: Variable[],
): Partial<Condition> {
  if (!toColumn) return { other_variable: null }
  return {
    other_variable:
      condition.other_variable
      ?? variables.find((v) => v.name !== condition.variable)?.name
      ?? condition.variable,
    operator: COLUMN_OPERATORS.includes(condition.operator) ? condition.operator : 'eq',
    value: '',
    use_label: false,
  }
}

/** How deep the groups can nest before the indentation stops helping. */
const MAX_DEPTH = 3

export const emptyFilter = (): FilterGroup => ({ op: 'and', conditions: [], groups: [] })

const MULTI: FilterOperator[] = ['in', 'not_in', 'between']

/** Row-per-condition filter editor. Values are sent as-is and bound server side. */
export default function FilterBuilder({
  variables,
  value,
  onChange,
  /**
   * Offer "another variable" as the right hand side of a comparison.
   *
   * Off by default: scoping a query to a region wants a literal, and a third
   * select on every row earns its place only where comparing two columns is
   * the point, which today is the logic check.
   */
  allowVariableComparison = false,
  depth = 0,
  onRemoveGroup,
}: {
  variables: Variable[]
  value: FilterGroup
  onChange: (next: FilterGroup) => void
  allowVariableComparison?: boolean
  depth?: number
  onRemoveGroup?: () => void
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

  const addGroup = () =>
    onChange({ ...value, groups: [...value.groups, emptyFilter()] })

  const updateGroup = (index: number, next: FilterGroup) =>
    onChange({ ...value, groups: value.groups.map((g, i) => (i === index ? next : g)) })

  const removeGroup = (index: number) =>
    onChange({ ...value, groups: value.groups.filter((_, i) => i !== index) })

  const setSide = (index: number, condition: Condition, toColumn: boolean) =>
    update(index, sideSwitch(condition, toColumn, variables))

  // One group among several, or a subgroup, needs a line around it: without
  // one, "any of" sitting above a flat run of rows reads as applying to all of
  // them rather than to the bracket.
  const bracketed = depth > 0
  const rows = value.conditions.length + value.groups.length

  return (
    <div
      className={
        bracketed
          ? 'space-y-2 rounded-lg border border-ink-200 bg-ink-50/40 p-2.5 dark:border-slate-700 dark:bg-slate-900/40'
          : 'space-y-2'
      }
    >
      {(rows > 1 || bracketed) && (
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
          of these
          {onRemoveGroup && (
            <button
              className="btn-ghost btn-sm ml-auto text-red-600"
              onClick={onRemoveGroup}
              aria-label="Remove group"
            >
              Remove group
            </button>
          )}
        </div>
      )}

      {value.conditions.map((condition, index) => {
        const againstColumn = Boolean(condition.other_variable)
        const offered = againstColumn
          ? OPERATORS.filter((o) => COLUMN_OPERATORS.includes(o.value))
          : OPERATORS
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
                  {v.label ? `${v.name} - ${v.label}` : v.name}
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
              {offered.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>

            {allowVariableComparison && !operator?.noValue && (
              <select
                className="input w-28 py-1.5 text-xs"
                value={againstColumn ? 'variable' : 'value'}
                onChange={(event) =>
                  setSide(index, condition, event.target.value === 'variable')
                }
                aria-label="Compare against"
              >
                <option value="value">a value</option>
                <option value="variable">a variable</option>
              </select>
            )}

            {!operator?.noValue &&
              (againstColumn ? (
                <select
                  className="input w-44 py-1.5 text-xs"
                  value={String(condition.other_variable ?? '')}
                  onChange={(event) =>
                    update(index, { other_variable: event.target.value })
                  }
                >
                  {variables.map((v) => (
                    <option key={v.name} value={v.name}>
                      {v.label ? `${v.name} - ${v.label}` : v.name}
                    </option>
                  ))}
                </select>
              ) : options.length > 0 && ['eq', 'ne'].includes(condition.operator) ? (
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
                    MULTI.includes(condition.operator) ? 'comma separated' : 'value'
                  }
                  value={
                    Array.isArray(condition.value)
                      ? condition.value.join(', ')
                      : String(condition.value ?? '')
                  }
                  onChange={(event) => {
                    const raw = event.target.value
                    update(index, {
                      value: MULTI.includes(condition.operator)
                        ? raw.split(',').map((part) => part.trim())
                        : raw,
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

      {value.groups.map((group, index) => (
        <FilterBuilder
          key={index}
          variables={variables}
          value={group}
          onChange={(next) => updateGroup(index, next)}
          allowVariableComparison={allowVariableComparison}
          depth={depth + 1}
          onRemoveGroup={() => removeGroup(index)}
        />
      ))}

      <div className="flex flex-wrap gap-2">
        <button
          className="btn-secondary btn-sm"
          onClick={add}
          disabled={!variables.length}
        >
          + Add filter
        </button>
        {depth < MAX_DEPTH && (
          <button
            className="btn-ghost btn-sm"
            onClick={addGroup}
            disabled={!variables.length}
            title="A bracket, for mixing and with or"
          >
            + Add group
          </button>
        )}
      </div>
    </div>
  )
}
