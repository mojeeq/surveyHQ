/**
 * What a shelf of datasets adds up to.
 *
 * Pure, and kept out of the page, because the page's job is layout and this is
 * arithmetic that wants testing without a browser. A collapsed project row is
 * otherwise a name and a count, which does not say whether anything in there
 * needs attention or whether the project has been touched this month.
 *
 * Deliberately not here: a total row count. It is the number easiest to add up
 * and the one least worth reading - nobody decides anything differently on
 * seeing that a workspace holds 25,572 rows rather than 25,000.
 */

export interface Countable {
  file_size: number
  status: string
  updated_at: string
}

export interface Totals {
  /** How many datasets are on the shelf. */
  count: number
  bytes: number
  /** Anything not yet usable: still processing, or failed outright. */
  unready: number
  /**
   * Datasets whose data was deliberately removed and whose charts are still
   * attached, waiting for the export to be uploaded again. Counted apart from
   * `unready` because nothing has gone wrong with one of these, and a red
   * badge over a state somebody chose reads as a fault that needs chasing.
   */
  waiting: number
  /** The most recent touch, or null when the shelf is empty. */
  updated: string | null
}

export function summarise(datasets: readonly Countable[]): Totals {
  let bytes = 0
  let unready = 0
  let waiting = 0
  let updated: string | null = null
  for (const dataset of datasets) {
    bytes += dataset.file_size || 0
    if (dataset.status === 'archived') waiting += 1
    else if (dataset.status !== 'ready') unready += 1
    if (dataset.updated_at && (updated === null || dataset.updated_at > updated)) {
      updated = dataset.updated_at
    }
  }
  return { count: datasets.length, bytes, unready, waiting, updated }
}
