/**
 * The settings of a likely-duplicates check, as the form edits them.
 *
 * The check itself is on the server (services/likely_duplicates.py): it scores
 * every pair of records field by field and flags the pairs alike enough to be
 * one person entered twice. What is decided here is how the form starts - which
 * way a variable is compared when it is first chosen, guessed from what it
 * holds - so somebody who picks "first_name" and "age" gets a spelling
 * comparison and a number within one year without being asked.
 */
import type { Variable } from '@/lib/types'

export type CompareMethod = 'text' | 'number' | 'date' | 'exact'

export interface DuplicateField {
  variable: string
  /** Further variables joined to it before comparing: a name kept in parts. */
  also?: string[]
  compare: CompareMethod
  weight?: number
  tolerance?: number
}

export interface DuplicateBlock {
  variable: string
  how: 'same' | 'first_letter'
}

export interface LikelyDuplicatesConfig {
  fields?: DuplicateField[]
  block?: DuplicateBlock[]
  id_variables?: string[]
  min_similarity?: number
}

/** The ways a field can be compared, as the form offers them. */
export const COMPARE_METHODS: {
  value: CompareMethod
  label: string
  /** What the tolerance box means, where the method has one. */
  tolerance?: string
  hint: string
}[] = [
  {
    value: 'text',
    label: 'Similar spelling',
    hint: 'For names. Case, accents, punctuation and the order of the words are ignored, and a letter or two different still counts as close.',
  },
  {
    value: 'number',
    label: 'Number within ±',
    tolerance: 'within ±',
    hint: 'An age, a household size. Alike when no further apart than the tolerance.',
  },
  {
    value: 'date',
    label: 'Date within ± days',
    tolerance: 'days',
    hint: 'A date of birth. Alike within the tolerance, or with the day and month swapped.',
  },
  {
    value: 'exact',
    label: 'Exactly the same',
    hint: 'A code: sex, a village, a relationship to the head.',
  },
]

/** Words in a variable's name that say it holds a person's name. */
const NAME_WORDS = ['name', 'names', 'firstname', 'surname', 'lastname', 'fullname', 'forename', 'givenname']

/** How alike a pair has to be, when nobody has said. */
export const DEFAULT_SIMILARITY = 0.9

/**
 * How to compare a variable chosen for the first time.
 *
 * A date is a date; a number is a number, compared within a year when it is
 * an age, since an age is the answer most often off by one; a name - by what
 * the variable is called, or a column of many different values - is compared
 * by spelling, at twice the weight, because a name says more about who someone
 * is than anything else on the form; anything else is a code, compared
 * exactly. A name is told by what it is called before by how many values it
 * has: in a small file a first name has few values and would look like a code.
 */
export function guessField(variable: Variable): DuplicateField {
  const words = variable.name.toLowerCase().split(/[^a-z0-9]+/)
  if (words.some((word) => NAME_WORDS.includes(word))) {
    return { variable: variable.name, compare: 'text', weight: 2 }
  }
  if (variable.var_type === 'datetime' || words.some((word) => ['dob', 'birth', 'birthdate'].includes(word))) {
    return { variable: variable.name, compare: 'date', tolerance: 0, weight: 1 }
  }
  if (variable.var_type === 'numeric') {
    return {
      variable: variable.name,
      compare: 'number',
      tolerance: words.includes('age') ? 1 : 0,
      weight: 1,
    }
  }
  const labelled = Object.keys(variable.value_labels ?? {}).length > 0
  if (variable.var_type === 'text' || (!labelled && (variable.n_unique ?? 0) > 50)) {
    return { variable: variable.name, compare: 'text', weight: 2 }
  }
  return { variable: variable.name, compare: 'exact', weight: 1 }
}

/** What the form says the check will do, in a sentence, before it is saved. */
export function describe(config: LikelyDuplicatesConfig): string {
  const fields = (config.fields ?? []).filter((field) => field.variable)
  if (fields.length < 2) return 'Choose at least two fields to compare - a name and an age, say.'
  const alike = Math.round((config.min_similarity ?? DEFAULT_SIMILARITY) * 100)
  const within = (config.block ?? []).filter((block) => block.variable)
  const where = within.length
    ? ` within the same ${within
        .map((block) => (block.how === 'first_letter' ? `first letter of ${block.variable}` : block.variable))
        .join(' and ')}`
    : ''
  return `Flags pairs of records at least ${alike}% alike on ${fields
    .map((field) => [field.variable, ...(field.also ?? []).filter(Boolean)].join(' + '))
    .join(', ')}${where}.`
}
