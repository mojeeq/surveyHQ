/**
 * Writing an indicator as arithmetic over named parts.
 *
 * An indicator used to be one count and a switch saying "as a share of every
 * record". That answers "how many" and "what share of everything" and stops
 * there, so the numbers a survey office actually reports - refusals per
 * completed interview, the share among those who answered one question, the
 * gap between households visited and households interviewed - were worked out
 * on paper beside the dashboard.
 *
 * Here each part is counted on its own terms, under a name, and a formula
 * combines them. The point of the screen is that nothing has to be saved to
 * be checked: the parts and the answer are read back from the server as they
 * are typed, so "17 over 0" is visible here rather than as a blank tile later.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import FilterBuilder, { emptyFilter } from '@/components/FilterBuilder'
import { measurable, weighted } from '@/lib/measures'
import { api } from '@/lib/api'
import { formatNumber, formatValue } from '@/lib/format'
import type { Aggregation, FormulaPart, Variable } from '@/lib/types'

/** The aggregates a part may be, in the words the rest of the form uses. */
export const PART_MEASURES: {
  value: string
  label: string
  agg: Aggregation
  needsVariable: boolean
  numericOnly: boolean
}[] = [
  { value: 'records', label: 'Records', agg: 'count', needsVariable: false, numericOnly: false },
  {
    value: 'answered',
    label: 'Records answering',
    agg: 'count',
    needsVariable: true,
    numericOnly: false,
  },
  { value: 'sum', label: 'Sum of', agg: 'sum', needsVariable: true, numericOnly: true },
  { value: 'mean', label: 'Mean of', agg: 'mean', needsVariable: true, numericOnly: true },
  {
    value: 'distinct',
    label: 'Different values of',
    agg: 'count_distinct',
    needsVariable: true,
    numericOnly: false,
  },
]

/**
 * Which kind a part is, read back off the part itself.
 *
 * The select holds no state of its own, so this is what keeps a choice on
 * screen. A variable of `null` means the measure takes none; an empty one
 * means it takes one that has not been picked yet. Telling those apart is the
 * whole of it: reading "unchosen" as "takes none" sent every option that needs
 * a variable straight back to Records, which made a part a row count and
 * nothing else.
 */
export const kindOf = (part: FormulaPart) => {
  const named = part.measure.variable !== null && part.measure.variable !== undefined
  const found = PART_MEASURES.find(
    (one) => one.agg === part.measure.agg && one.needsVariable === named,
  )
  return found?.value ?? 'records'
}

/** The measure a chosen kind starts as, with its variable still to pick. */
export function measureFor(kind: string): { agg: Aggregation; variable: string | null } {
  const found = PART_MEASURES.find((one) => one.value === kind) ?? PART_MEASURES[0]
  return { agg: found.agg, variable: found.needsVariable ? '' : null }
}

/** Whether a part is finished enough to be counted. */
export const isReady = (part: FormulaPart) =>
  Boolean(part.name) &&
  (PART_MEASURES.find((one) => one.value === kindOf(part))?.needsVariable
    ? Boolean(part.measure.variable)
    : true)

/** Whether every part is, which is when the trial below is worth asking for. */
export const allReady = (parts: FormulaPart[]) => parts.every(isReady)

/** A name nobody has used yet: part_1, part_2, and so on. */
export function freeName(parts: FormulaPart[]): string {
  const taken = new Set(parts.map((part) => part.name))
  for (let n = 1; n < 100; n += 1) {
    if (!taken.has(`part_${n}`)) return `part_${n}`
  }
  return `part_${parts.length + 1}`
}

/** What a part's name may be, which is what the formula can refer to. */
export const tidyName = (typed: string) =>
  typed.replace(/[^A-Za-z0-9_]/g, '_').replace(/^[0-9]/, '_')

export function FormulaBuilder({
  datasetId,
  variables,
  parts,
  expression,
  format,
  weight = '',
  onParts,
  onExpression,
}: {
  datasetId: string
  variables: Variable[]
  parts: FormulaPart[]
  expression: string
  /** How the tile will print the answer, so the trial reads the same way. */
  format: string
  /** The indicator's survey weight, so the trial is weighted as the tile
   *  will be. */
  weight?: string
  onParts: (next: FormulaPart[]) => void
  onExpression: (next: string) => void
}) {
  // Asked of the server a moment after typing stops, rather than on every
  // keystroke: each check is a query per part, and a formula is typed slowly
  // by somebody thinking about it.
  const [settled, setSettled] = useState(expression)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(expression), 600)
    return () => clearTimeout(timer)
  }, [expression])

  const asked = parts.map((part) => ({ ...part, measure: weighted(part.measure, weight) }))
  const check = useQuery({
    queryKey: ['formula-preview', datasetId, settled, JSON.stringify(asked)],
    queryFn: () =>
      api.post<{
        value: number | null
        parts: Record<string, number | null>
        error: string | null
      }>('/monitoring/formula-preview', {
        dataset_id: datasetId,
        formula: { expression: settled, parts: asked },
      }),
    // A part whose variable has not been chosen cannot be counted, and asking
    // anyway answers with a validation error about an empty variable - which
    // is a complaint about a form somebody is still filling in.
    enabled: Boolean(datasetId && settled.trim() && parts.length > 0 && allReady(parts)),
    retry: false,
  })

  const change = (index: number, patch: Partial<FormulaPart>) =>
    onParts(parts.map((part, at) => (at === index ? { ...part, ...patch } : part)))

  // Anything stored as a number: see lib/measures for why the importer's
  // judgement must not decide what can be measured.
  const numeric = measurable(variables)

  return (
    <div className="space-y-3">
      {parts.map((part, index) => {
        const kind = kindOf(part)
        const measure = PART_MEASURES.find((one) => one.value === kind)!
        const choices = measure.numericOnly ? numeric : variables
        return (
          <div
            key={index}
            className="rounded-lg border border-ink-200 p-3 dark:border-dark-200"
          >
            <div className="flex flex-wrap items-end gap-2">
              <label className="block text-xs text-ink-500 dark:text-dark-500">
                <span className="block">Call it</span>
                <input
                  className="input mt-1 w-36"
                  value={part.name}
                  onChange={(event) =>
                    change(index, { name: tidyName(event.target.value) })
                  }
                  placeholder="done"
                />
              </label>
              <label className="block text-xs text-ink-500 dark:text-dark-500">
                <span className="block">Count</span>
                <select
                  className="input mt-1 w-44"
                  value={kind}
                  onChange={(event) =>
                    change(index, { measure: measureFor(event.target.value) })
                  }
                >
                  {PART_MEASURES.map((one) => (
                    <option key={one.value} value={one.value}>
                      {one.label}
                    </option>
                  ))}
                </select>
              </label>
              {measure.needsVariable && (
                <label className="block text-xs text-ink-500 dark:text-dark-500">
                  <span className="block">
                    {measure.numericOnly ? 'Numeric variable' : 'Variable'}
                  </span>
                  <select
                    className="input mt-1 w-52"
                    value={part.measure.variable ?? ''}
                    onChange={(event) =>
                      change(index, {
                        measure: { ...part.measure, variable: event.target.value },
                      })
                    }
                  >
                    <option value="">Choose a variable…</option>
                    {choices.map((one) => (
                      <option key={one.name} value={one.name}>
                        {one.label ? `${one.name} - ${one.label}` : one.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                className="btn-ghost ml-auto text-xs"
                onClick={() => onParts(parts.filter((_, at) => at !== index))}
              >
                Remove
              </button>
            </div>
            <div className="mt-2">
              <p className="mb-1 text-xs text-ink-500 dark:text-dark-500">
                Only the records where
              </p>
              <FilterBuilder
                variables={variables}
                value={part.filters}
                onChange={(next) => change(index, { filters: next })}
              />
            </div>
            {!isReady(part) && (
              <p className="mt-2 text-xs text-ink-400 dark:text-dark-400">
                Choose a variable for this part to see what it counts.
              </p>
            )}
            {check.data?.parts?.[part.name] !== undefined && (
              <p className="mt-2 text-xs text-ink-500 dark:text-dark-500">
                {part.name} counts{' '}
                <span className="font-medium text-ink-700 dark:text-dark-700">
                  {check.data.parts[part.name] === null
                    ? 'nothing'
                    : formatNumber(check.data.parts[part.name] as number)}
                </span>{' '}
                right now
              </p>
            )}
          </div>
        )
      })}

      <button
        className="btn-secondary text-xs"
        onClick={() =>
          onParts([
            ...parts,
            {
              name: freeName(parts),
              measure: { agg: 'count', variable: null },
              filters: emptyFilter(),
            },
          ])
        }
      >
        Add a part
      </button>

      <label className="block text-xs text-ink-500 dark:text-dark-500">
        <span className="block">The formula</span>
        <input
          className="input mt-1 font-mono"
          value={expression}
          onChange={(event) => onExpression(event.target.value)}
          placeholder="done / issued * 100"
        />
      </label>
      <p className="text-xs text-ink-400 dark:text-dark-400">
        The part names, numbers, + - * / and brackets. A percentage is a
        division and a hundred: <code>done / issued * 100</code>.
      </p>

      {/* What it says, now, against the data it is being written against.
          A formula is wrong until it is not, and the slow way to find that
          out is to save it and read the tile. */}
      {check.isError && (
        <p className="text-xs text-rose-700 dark:text-rose-400">
          {(check.error as Error).message}
        </p>
      )}
      {check.data?.error && (
        <p className="text-xs text-rose-700 dark:text-rose-400">{check.data.error}</p>
      )}
      {check.data && !check.data.error && (
        <p className="text-xs text-ink-600 dark:text-dark-600">
          Right now that comes to{' '}
          <span className="font-medium text-ink-900 dark:text-dark-900">
            {check.data.value === null
              ? 'nothing - there is nothing to divide by'
              : formatValue(check.data.value, format)}
          </span>
        </p>
      )}
    </div>
  )
}
