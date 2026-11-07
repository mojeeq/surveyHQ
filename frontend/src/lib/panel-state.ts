/**
 * What a panel on the Overview may claim, given what its requests returned.
 *
 * The rule is simple: a panel only says "nothing here" (an empty state or an
 * all-clear) when the request behind it has just succeeded. A failed request
 * is an error, not an empty list, and figures kept from an earlier request
 * after a refresh failed are marked as out of date.
 */

/** The parts of a TanStack Query result these functions read. */
export interface QuerySnapshot<T> {
  data: T | undefined
  error: unknown
  /** When the data shown was last fetched successfully (ms since epoch, 0 if never). */
  dataUpdatedAt?: number
}

export type PanelState<T> =
  | { state: 'loading' }
  | { state: 'error'; error: unknown }
  | { state: 'empty' }
  | { state: 'ready'; data: T }
  /** Data from an earlier request, shown because the latest refresh failed. */
  | { state: 'stale'; data: T; error: unknown; updatedAt: number }

export function panelState<T>(query: QuerySnapshot<T>, isEmpty: (data: T) => boolean): PanelState<T> {
  const { data, error } = query
  if (data === undefined) return error ? { state: 'error', error } : { state: 'loading' }
  if (error) {
    // An empty result from before a failed refresh proves nothing about now,
    // so it is reported as the failure rather than as "nothing here".
    if (isEmpty(data)) return { state: 'error', error }
    return { state: 'stale', data, error, updatedAt: query.dataUpdatedAt ?? 0 }
  }
  return isEmpty(data) ? { state: 'empty' } : { state: 'ready', data }
}

/** One source of the Needs attention panel, and what it is called if it fails. */
export interface AttentionSource<T> {
  label: string
  query: QuerySnapshot<T[]>
}

export type AttentionPanel<A, B> =
  | { state: 'loading' }
  | { state: 'error'; error: unknown; failed: string[] }
  /** Every source answered, and none of them found anything. */
  | { state: 'clear' }
  | {
      state: 'items'
      first: A[]
      second: B[]
      /** Sources that could not be checked or refreshed, so the list may be incomplete. */
      failed: string[]
      /** True when some of what is listed comes from before a failed refresh. */
      stale: boolean
    }

/**
 * Needs attention lists two things at once: problems (failing checks, failed
 * imports and so on) and open alerts. "Nothing is flagged" needs both to have
 * answered; one failing while the other is empty is a failure, not an all-clear.
 */
export function attentionPanel<A, B>(
  first: AttentionSource<A>,
  second: AttentionSource<B>,
): AttentionPanel<A, B> {
  const a = first.query.data ?? []
  const b = second.query.data ?? []
  const failed = [first, second].filter((source) => source.query.error).map((source) => source.label)
  const stale = [first, second].some((source) => source.query.error && source.query.data?.length)

  if (a.length || b.length) return { state: 'items', first: a, second: b, failed, stale }
  const error = first.query.error || second.query.error
  if (error) return { state: 'error', error, failed }
  if (first.query.data === undefined || second.query.data === undefined) return { state: 'loading' }
  return { state: 'clear' }
}
