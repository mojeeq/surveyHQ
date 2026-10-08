import type { FilterGroup, Variable } from '@/lib/types'

/**
 * Starting points for a logic condition.
 *
 * A preset fills the builder in rather than being its own check type. The
 * alternative was a second form per shape, which is how Cross-variable
 * consistency came to exist as a check that could only ever compare one pair
 * of variables with one operator: once it is a preset, widening it is just
 * adding another row.
 */
export interface LogicPreset {
  id: string
  label: string
  hint: string
  /** Which side of the condition is the problem. See the Quality page. */
  flag: 'match' | 'no_match'
  build: (variables: Variable[]) => FilterGroup
}

/**
 * The two variables a pairwise preset starts on.
 *
 * Two of the same orderable type, dates before numbers. Comparing one column
 * with another only means something when both can be put in order, and only
 * reads sensibly when they are the same kind of thing: a date against a count
 * is a guess nobody wants. Dates come first because a start and an end are
 * the classic pair, and a dataset holding two of them almost certainly wants
 * them - which is also the example the form gives.
 *
 * `categorical` is left out although integer code sets sort perfectly well.
 * It is where a survey's 1/2 answer codes land, and "sex at most region" is a
 * worse opening guess than anything it would displace.
 *
 * Falls back to the first two of whatever exists, and to the same variable
 * twice when the dataset has only one: useless as a rule and visibly so,
 * which beats a row with an empty select that silently will not save.
 */
const ORDERABLE = ['datetime', 'numeric'] as const

export function firstPair(variables: Variable[]): [string, string] {
  const sameType = ORDERABLE.map((type) =>
    variables.filter((v) => v.var_type === type),
  ).find((group) => group.length >= 2)
  const pool = sameType ?? variables
  const left = pool[0]?.name ?? ''
  const right = pool[1]?.name ?? left
  return [left, right]
}

export const LOGIC_PRESETS: LogicPreset[] = [
  {
    id: 'consistency',
    label: 'Cross-variable consistency',
    hint: 'One variable against another, the way the old check read: state the relationship that must hold and the rows breaking it are flagged.',
    // The retired check stated what must be true and counted the violations,
    // so the preset opens in the same direction. Anyone who thinks of it as
    // "flag the bad rows" can switch it above without losing the condition.
    flag: 'no_match',
    build: (variables) => {
      const [left, right] = firstPair(variables)
      return {
        op: 'and',
        conditions: [
          { variable: left, operator: 'lte', value: '', use_label: false, other_variable: right },
        ],
        groups: [],
      }
    },
  },
]
