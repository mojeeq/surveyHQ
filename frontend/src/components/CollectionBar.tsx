/**
 * The row of controls above a list of things: search, order, and how to show it.
 *
 * Projects and dashboards both have one, and it is one component so that the
 * two pages cannot drift into behaving differently. The page owns the state and
 * the options; this owns what the controls look like and how they are labelled.
 */

import type { ReactNode } from 'react'
import type { Direction } from '@/lib/collections'

export type ViewMode = 'cards' | 'list'
export const VIEW_MODES: readonly ViewMode[] = ['cards', 'list']

export interface SortOption {
  /** Matches a key in the page's own table of readers. */
  key: string
  label: string
}

export default function CollectionBar({
  noun,
  shown,
  total,
  query,
  onQuery,
  sort,
  onSort,
  direction,
  onDirection,
  options,
  view,
  onView,
  children,
}: {
  /** Singular, for the count: "3 of 12 projects". */
  noun: string
  shown: number
  total: number
  query: string
  onQuery: (value: string) => void
  sort: string
  onSort: (value: string) => void
  direction: Direction
  onDirection: (value: Direction) => void
  options: SortOption[]
  view: ViewMode
  onView: (value: ViewMode) => void
  /** A filter belonging to this page alone, placed beside the search box. */
  children?: ReactNode
}) {
  const narrowed = shown !== total
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <input
        className="input max-w-xs"
        type="search"
        placeholder={`Search ${noun}s…`}
        value={query}
        onChange={(event) => onQuery(event.target.value)}
        aria-label={`Search ${noun}s`}
      />
      {children}

      <label className="flex items-center gap-2 text-sm text-ink-600 dark:text-dark-600">
        Sort
        <select
          className="input w-auto py-1.5"
          value={sort}
          onChange={(event) => onSort(event.target.value)}
        >
          {options.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <button
        className="btn-secondary btn-sm"
        onClick={() => onDirection(direction === 'asc' ? 'desc' : 'asc')}
        // The arrow alone is not the label: it is the same glyph whichever way
        // the list is sorted, and a screen reader would read it as nothing.
        aria-label={direction === 'asc' ? 'Sorted ascending' : 'Sorted descending'}
        title={direction === 'asc' ? 'Ascending. Click for descending.' : 'Descending. Click for ascending.'}
      >
        {direction === 'asc' ? '↑' : '↓'}
      </button>

      <span className="text-xs text-ink-500 dark:text-dark-500">
        {narrowed ? `${shown} of ${total}` : total} {noun}
        {total === 1 && !narrowed ? '' : 's'}
      </span>
      {query && (
        <button className="btn-ghost btn-sm" onClick={() => onQuery('')}>
          Clear search
        </button>
      )}

      <div className="ml-auto flex overflow-hidden rounded-control border border-ink-200 dark:border-dark-300">
        {VIEW_MODES.map((mode) => (
          <button
            key={mode}
            onClick={() => onView(mode)}
            aria-pressed={view === mode}
            className={`px-3 py-1.5 text-sm capitalize ${
              view === mode
                ? 'bg-brand-600 text-white'
                : 'bg-white text-ink-600 hover:bg-ink-50 dark:bg-dark-100 dark:text-dark-600 dark:hover:bg-dark-200'
            }`}
          >
            {mode}
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * A table heading that sorts the list by its own column.
 *
 * The select in the bar above does the same job, and both drive the same state,
 * so a list sorted by clicking a heading shows that order in the select too.
 */
export function SortHeader({
  label,
  column,
  sort,
  direction,
  onSort,
  align = 'left',
}: {
  label: string
  column: string
  sort: string
  direction: Direction
  onSort: (column: string, direction: Direction) => void
  align?: 'left' | 'right'
}) {
  const active = sort === column
  return (
    <th
      className={`whitespace-nowrap px-3 py-2 font-medium ${
        align === 'right' ? 'text-right' : 'text-left'
      }`}
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        // `uppercase` is repeated from the thead rather than inherited: a
        // button does not take text-transform from its ancestors, so without
        // it the sortable headings sat in sentence case beside the plain ones
        // in capitals.
        className={`inline-flex items-center gap-1 uppercase hover:text-brand-700 dark:hover:text-brand-400 ${
          active ? 'text-ink-900 dark:text-dark-900' : ''
        }`}
        // Clicking the column already sorted turns it round; clicking another
        // starts that one ascending, which is what every table does.
        onClick={() => onSort(column, active && direction === 'asc' ? 'desc' : 'asc')}
      >
        {label}
        <span aria-hidden="true" className="text-xs">
          {active ? (direction === 'asc' ? '↑' : '↓') : ''}
        </span>
      </button>
    </th>
  )
}
