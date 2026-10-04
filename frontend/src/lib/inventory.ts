/**
 * What a shelf of datasets adds up to.
 *
 * Pure, and kept out of the page, because the page's job is layout and this is
 * arithmetic that wants testing without a browser. A collapsed project row is
 * otherwise a name and a count, which tells somebody nothing about whether the
 * project holds one large export or forty small ones.
 */

export interface Countable {
  row_count: number
  file_size: number
  status: string
  updated_at: string
}

export interface Totals {
  /** How many datasets are on the shelf. */
  count: number
  rows: number
  bytes: number
  /** Anything not yet usable: still processing, or failed outright. */
  unready: number
  /** The most recent touch, or null when the shelf is empty. */
  updated: string | null
}

export function summarise(datasets: readonly Countable[]): Totals {
  let rows = 0
  let bytes = 0
  let unready = 0
  let updated: string | null = null
  for (const dataset of datasets) {
    // A dataset still importing reports 0 rows rather than its eventual count,
    // so these are totals of what is actually readable today.
    rows += dataset.row_count || 0
    bytes += dataset.file_size || 0
    if (dataset.status !== 'ready') unready += 1
    if (dataset.updated_at && (updated === null || dataset.updated_at > updated)) {
      updated = dataset.updated_at
    }
  }
  return { count: datasets.length, rows, bytes, unready, updated }
}

/**
 * One group's share of the whole, as a fraction.
 *
 * Zero rather than NaN when there is nothing to divide by: an empty workspace
 * draws an empty bar, not a broken one. Clamped because a caller that passes a
 * part larger than the whole has a bug, and a bar overflowing its track hides
 * that bug behind a layout glitch.
 */
export function share(part: number, whole: number): number {
  if (!whole || whole <= 0) return 0
  return Math.max(0, Math.min(1, part / whole))
}
