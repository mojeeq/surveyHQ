import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'

import {
  parseFilter,
  printConditionText,
  printFilter,
  type ExpressionError,
} from '@/lib/filter-expression'
import type { Condition, FilterGroup, FilterOperator, Variable } from '@/lib/types'

// The editor is CodeMirror, and only somebody who switches to an expression
// needs it.
const FilterExpressionBox = lazy(() => import('@/components/FilterExpressionBox'))

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
  // A "tick all that apply" option. Like the two above, the column is the
  // answer, so there is no value to type.
  { value: 'selected', label: 'was ticked', noValue: true },
  { value: 'not_selected', label: 'was not ticked', noValue: true },
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

type Mode = 'builder' | 'expression'

/** Which way filters are written, remembered for the next one opened. */
const MODE_KEY = 'surveyhq.filter-mode'

function rememberedMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === 'expression' ? 'expression' : 'builder'
  } catch {
    return 'builder'
  }
}

/**
 * A filter, written row by row or as an expression.
 *
 * Both are the same filter: the expression is read into the groups and rows
 * the builder edits, and the builder's filter is printed as the expression,
 * so switching either way keeps what was there. The choice is remembered, so
 * somebody who writes expressions gets the box every time.
 */
export default function FilterBuilder(props: {
  variables: Variable[]
  value: FilterGroup
  onChange: (next: FilterGroup) => void
  allowVariableComparison?: boolean
}) {
  const { variables, value, onChange } = props
  const [mode, setMode] = useState<Mode>(rememberedMode)

  const choose = (next: Mode) => {
    setMode(next)
    try {
      localStorage.setItem(MODE_KEY, next)
    } catch {
      // Remembering is a convenience; the switch itself still happens.
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <div className="inline-flex rounded-control border border-ink-200 p-0.5 text-xs" role="group" aria-label="Write the filter as">
          {(['builder', 'expression'] as const).map((one) => (
            <button
              key={one}
              type="button"
              className={`rounded-control px-2.5 py-0.5 ${
                mode === one
                  ? 'bg-ink-100 font-medium text-ink-900 dark:bg-slate-700 dark:text-slate-100'
                  : 'text-ink-500 hover:text-ink-800'
              }`}
              aria-pressed={mode === one}
              onClick={() => choose(one)}
            >
              {one === 'builder' ? 'Builder' : 'Expression'}
            </button>
          ))}
        </div>
      </div>
      {mode === 'builder' ? (
        <FilterRows {...props} />
      ) : (
        <FilterExpression variables={variables} value={value} onChange={onChange} />
      )}
    </div>
  )
}

/**
 * The filter as one line of text: `sex == "Female" && age.InRange(15, 49)`.
 *
 * Every change that reads is applied at once, so the page behind shows what
 * the expression says while it is typed. One that does not read is
 * underlined where it went wrong and left unapplied: the filter in use stays
 * the last one that read, rather than turning into something half-typed.
 */
function FilterExpression({
  variables,
  value,
  onChange,
}: {
  variables: Variable[]
  value: FilterGroup
  onChange: (next: FilterGroup) => void
}) {
  const [text, setText] = useState(() => printFilter(value, variables))
  const [problem, setProblem] = useState<ExpressionError | null>(null)
  // What is wrong, said once the typing stops. Half a name is not a mistake
  // yet, and underlining every word on its way to being written is noise.
  const [shown, setShown] = useState<ExpressionError | null>(null)
  useEffect(() => {
    if (!problem) {
      setShown(null)
      return
    }
    const wait = window.setTimeout(() => setShown(problem), 700)
    return () => window.clearTimeout(wait)
  }, [problem])
  // The filter this box last handed up. When the one coming back down says
  // something else, it was changed from outside - a preset, a reset - and
  // the text is written afresh from it. Compared as printed, so a page that
  // copies the filter it is given does not rewrite the text being typed.
  const sent = useRef(printFilter(value, variables))

  useEffect(() => {
    const printed = printFilter(value, variables)
    if (printed === sent.current) return
    sent.current = printed
    setText(printed)
    setProblem(null)
  }, [value, variables])

  const type = (next: string) => {
    setText(next)
    const read = parseFilter(next, variables)
    if (!read.ok) {
      setProblem(read.error)
      return
    }
    setProblem(null)
    sent.current = printFilter(read.filter, variables)
    onChange(read.filter)
  }

  // The box is made once with the variables it colours and offers; another
  // dataset's variables make a new one.
  const names = useMemo(() => variables.map((one) => one.name).join('\u0000'), [variables])

  return (
    <div className="space-y-1.5">
      <div className="input expression-shell px-3">
        <Suspense fallback={<div className="py-1.5 font-mono text-[13px] text-ink-500">{text || ' '}</div>}>
          <FilterExpressionBox
            key={names}
            value={text}
            onChange={type}
            variables={variables}
            error={shown ? { from: shown.from, to: shown.to } : null}
            label="Filter expression"
          />
        </Suspense>
      </div>
      {shown ? (
        <p className="text-xs text-red-600 dark:text-red-400" role="status">
          {shown.message}
        </p>
      ) : (
        !problem &&
        text.trim() && (
          <p className="text-xs text-emerald-700 dark:text-emerald-400" role="status">
            ✓ Reads correctly
          </p>
        )
      )}
      <details className="text-xs text-ink-500">
        <summary className="cursor-pointer select-none">How to write one</summary>
        <div className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-[11.5px] text-ink-700">
          {EXPRESSION_HELP.map(([code, meaning]) => (
            <div key={code} className="contents">
              <code>{code}</code>
              <span className="font-sans text-ink-500">{meaning}</span>
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}

/** The cheat sheet under the box. */
const EXPRESSION_HELP: [string, string][] = [
  ['age >= 15 && sex == 2', 'and: == != > >= < <='],
  ['district == "North" || district == "East"', 'or, with a label in quotes or a code'],
  ['!(a || b)', 'not, and brackets'],
  ['district.InList("North", "East", 3)', 'is one of'],
  ['age.InRange(15, 49)', 'between, both ends included'],
  ['name.Contains("ab")', 'also StartsWith, EndsWith'],
  ['IsAnswered(phone)', 'has an answer; !IsAnswered(phone) has none'],
  ['IsSelected(water__3)', 'a ticked option'],
  ['end_date < start_date', 'one variable against another'],
  ['inc2020 - inc2019 > 100', 'arithmetic: + - * / and brackets'],
  ['`my column` == 1', 'a name with spaces, in backticks'],
]

/** Row-per-condition filter editor. Values are sent as-is and bound server side. */
function FilterRows({
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
        // Arithmetic has no dropdowns to show it in. It is shown as written,
        // to be changed under Expression, and can still be removed here.
        if (condition.formula || condition.other_formula) {
          return (
            <div key={index} className="flex flex-wrap items-center gap-2">
              <code className="rounded-control border border-ink-200 bg-ink-50 px-2.5 py-1.5 font-mono text-xs text-ink-700">
                {printConditionText(condition, variables)}
              </code>
              <span className="text-xs text-ink-500">arithmetic - change it under Expression</span>
              <button
                className="btn-ghost btn-sm text-red-600"
                onClick={() => remove(index)}
                aria-label="Remove condition"
              >
                ✕
              </button>
            </div>
          )
        }
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
        <FilterRows
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
