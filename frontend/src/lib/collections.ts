/**
 * Narrowing and ordering a list of things, for the pages that show one.
 *
 * Projects and dashboards are both "a list of named things with some counts and
 * a date", and both wanted the same three controls: a search box, an order, and
 * a choice between cards and rows. Writing that twice would have meant two
 * search boxes that disagree about whether "palau census" should match "Palau
 * Census 2025" - which is the kind of difference nobody notices until somebody
 * reports that search is broken on one page and fine on the other.
 *
 * So the rules live here, once, and the pages pass in what to read.
 */

/** What a sort or a search can be given. Anything else is treated as blank. */
export type Sortable = string | number | null | undefined

export type Direction = 'asc' | 'desc'

/**
 * Whether one item answers what was typed in the search box.
 *
 * Every word must match something, but not all in the same field: "palau 2025"
 * finds a dashboard called "Palau Census" described as "2025 round", because
 * somebody searching types what they remember, not what is in one column.
 */
export function matches(query: string, fields: Sortable[]): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return true
  const haystack = fields
    .filter((field) => field !== null && field !== undefined)
    .map((field) => String(field).toLowerCase())
  return terms.every((term) => haystack.some((field) => field.includes(term)))
}

/** Blank, for sorting: nothing to order by, rather than a value of zero. */
function blank(value: Sortable): boolean {
  return value === null || value === undefined || value === ''
}

/**
 * A comparator that keeps blanks at the bottom whichever way it sorts.
 *
 * Reversing the direction must not float the rows with nothing in them to the
 * top: a project with no description is not the project with the
 * alphabetically-last description, and a list that opens on its own empty rows
 * looks broken.
 *
 * Text compares as a person reads it, so "Round 2" comes before "Round 10"
 * rather than after it, and case and accents do not split a name in two.
 */
export function by<T>(
  read: (item: T) => Sortable,
  direction: Direction = 'asc',
): (one: T, other: T) => number {
  const sign = direction === 'desc' ? -1 : 1
  return (one, other) => {
    const left = read(one)
    const right = read(other)
    if (blank(left) && blank(right)) return 0
    if (blank(left)) return 1
    if (blank(right)) return -1
    if (typeof left === 'number' && typeof right === 'number') return (left - right) * sign
    return (
      String(left).localeCompare(String(right), undefined, {
        numeric: true,
        sensitivity: 'base',
      }) * sign
    )
  }
}

/**
 * Search, then order. One call, so every list on the platform behaves alike.
 *
 * The sort is applied to a copy: the array handed in belongs to the query
 * cache, and sorting it where it lies would reorder it for every other reader
 * of the same data.
 */
export function arrange<T>(
  items: T[],
  options: {
    query?: string
    /** The fields the search box looks through. */
    searchable?: (item: T) => Sortable[]
    /** The field the order is taken from. */
    read?: (item: T) => Sortable
    direction?: Direction
  } = {},
): T[] {
  const { query = '', searchable, read, direction = 'asc' } = options
  const found =
    query.trim() && searchable
      ? items.filter((item) => matches(query, searchable(item)))
      : items.slice()
  // A copy either way, and sort is stable, so items the order cannot separate
  // stay in the order the server sent them.
  return read ? found.slice().sort(by(read, direction)) : found
}
