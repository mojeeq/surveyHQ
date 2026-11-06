/**
 * Variables brought into a dataset from another one, as the dataset page
 * shows and edits them.
 *
 * The work is on the server (services/linked_variables.py): the variables
 * are joined in by key, the dataset keeps its id, and they are brought in
 * again whenever either dataset gets new data. What is decided here is what
 * the form offers and how a link reads in a sentence.
 */
import type { Variable } from '@/lib/types'

export type KeyMatch = 'exact' | 'text' | 'number'

export interface LinkKey {
  here: string
  there: string
}

export interface LinkedVariables {
  id: string
  source_id: string
  source_name: string
  source_exists: boolean
  keys: LinkKey[]
  key_match: KeyMatch
  variables: string[]
  status: {
    status?: 'ok' | 'failed'
    message?: string
    at?: string
    rows?: number
    matched?: number
  }
}

export interface LinkCheck {
  keys: LinkKey[]
  key_match: KeyMatch
  error: string | null
  match: { rows: number; matched: number; unmatched: number; sentence: string } | null
}

export const KEY_MATCHES: { value: KeyMatch; label: string; hint: string }[] = [
  { value: 'exact', label: 'Exactly, as stored', hint: 'The two columns hold the ids the same way.' },
  { value: 'text', label: 'As text', hint: 'An id that is a number on one side and text on the other.' },
  {
    value: 'number',
    label: 'As numbers',
    hint: '"0041" and 41 count as the same: padding and a trailing .0 are ignored.',
  },
]

const COMPANION = '__mv'

/** A link in one line: "size, province from households, matched on hhid". */
export function describeLink(link: Pick<LinkedVariables, 'variables' | 'source_name' | 'keys' | 'key_match'>): string {
  const keys = link.keys
    .map((key) => (key.here === key.there ? key.here : `${key.here} = ${key.there}`))
    .join(' and ')
  const how = link.key_match === 'exact' ? '' : ` (${link.key_match === 'text' ? 'as text' : 'as numbers'})`
  return `${link.variables.join(', ')} from ${link.source_name}, matched on ${keys}${how}`
}

/** Which dataset each brought-in variable came from, by its name. */
export function broughtFrom(links: LinkedVariables[]): Record<string, string> {
  const from: Record<string, string> = {}
  for (const link of links) for (const name of link.variables) from[name] = link.source_name
  return from
}

export interface Offer {
  name: string
  label: string
  /** Why it cannot be chosen, where it cannot. */
  unavailable?: string
}

/**
 * The other dataset's variables, as the form offers them.
 *
 * The keys are left out - matched on, not brought across - and so are the
 * hidden companions of Stata's tagged missings, which travel with their
 * variable. One this dataset already has of its own is shown but cannot be
 * ticked: two columns with one name is not something to settle by guessing.
 */
export function offers(source: Variable[], target: Variable[], keys: LinkKey[], links: LinkedVariables[]): Offer[] {
  const keyNames = new Set(keys.map((key) => key.there))
  const brought = broughtFrom(links)
  const own = new Set(target.map((variable) => variable.name).filter((name) => !(name in brought)))
  return source
    .filter((variable) => !variable.name.endsWith(COMPANION) && !keyNames.has(variable.name))
    .map((variable) => ({
      name: variable.name,
      label: variable.label,
      unavailable: own.has(variable.name)
        ? `${variable.name} is already in this dataset`
        : variable.name in brought
          ? `Already brought in from ${brought[variable.name]}`
          : undefined,
    }))
}

/** The variables of this dataset that can be matched on: its own, not brought-in ones. */
export function ownVariables(target: Variable[], links: LinkedVariables[]): Variable[] {
  const brought = broughtFrom(links)
  return target.filter((variable) => !variable.name.endsWith(COMPANION) && !(variable.name in brought))
}
