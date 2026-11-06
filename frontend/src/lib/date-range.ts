/**
 * A dashboard's date-range filter: its choices, and the conditions they make.
 *
 * Dates were left out of a dashboard's filters - two hundred of them make a
 * dropdown nobody can use, and a date wants a range - so a fieldwork board
 * could not show today's interviews, or this week's. A date variable gets a
 * control of its own now: a named range, or two days of the reader's choosing.
 *
 * A choice is kept as text like any filter's value, so a saved view keeps it:
 * `dates:last_7`, or `dates:2026-11-01..2026-11-15` with either side free to
 * be empty. A named range stays relative - "Last 7 days" saved in a view is
 * the last seven days whenever the view is opened.
 *
 * Worked out here, in the reader's browser, so "today" is the reader's today.
 * The server has the same rule for files made from a saved view
 * (app/services/date_ranges.py); both are tested against the same cases.
 */
import type { Condition } from '@/lib/types'

export const DATE_PREFIX = 'dates:'

export const DATE_PRESETS: { value: string; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'last_7', label: 'Last 7 days' },
  { value: 'last_30', label: 'Last 30 days' },
  { value: 'this_week', label: 'This week' },
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
]

/** A calendar day, kept as one: no time and no zone to shift it. */
export interface Day {
  year: number
  month: number
  date: number
}

export function dayOf(moment: Date): Day {
  return { year: moment.getFullYear(), month: moment.getMonth() + 1, date: moment.getDate() }
}

function shift(day: Day, days: number): Day {
  return dayOf(new Date(day.year, day.month - 1, day.date + days))
}

export function iso(day: Day): string {
  return `${day.year}-${String(day.month).padStart(2, '0')}-${String(day.date).padStart(2, '0')}`
}

function parse(text: string): Day | null {
  const found = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text.trim())
  return found ? { year: Number(found[1]), month: Number(found[2]), date: Number(found[3]) } : null
}

/** The choice without its prefix: a preset's name, or `from..to`. */
export function choiceOf(value: string): string {
  return value.startsWith(DATE_PREFIX) ? value.slice(DATE_PREFIX.length) : value
}

/** The first day in the range and the first day after it. The end is the
 *  day after, so "up to the 15th" takes in the whole of the 15th. */
export function dateBounds(value: string, today: Day): { first: Day | null; after: Day | null } {
  const choice = choiceOf(value)
  const tomorrow = shift(today, 1)
  switch (choice) {
    case 'today':
      return { first: today, after: tomorrow }
    case 'yesterday':
      return { first: shift(today, -1), after: today }
    case 'last_7':
      return { first: shift(today, -6), after: tomorrow }
    case 'last_30':
      return { first: shift(today, -29), after: tomorrow }
    case 'this_week': {
      // From Monday, as an ISO week runs.
      const weekday = (new Date(today.year, today.month - 1, today.date).getDay() + 6) % 7
      return { first: shift(today, -weekday), after: tomorrow }
    }
    case 'this_month':
      return { first: { ...today, date: 1 }, after: tomorrow }
    case 'last_month': {
      const firstThis = { ...today, date: 1 }
      const lastOfPrevious = shift(firstThis, -1)
      return { first: { ...lastOfPrevious, date: 1 }, after: firstThis }
    }
    default: {
      const [start = '', end = ''] = choice.split('..')
      const first = parse(start)
      const last = parse(end)
      return { first, after: last ? shift(last, 1) : null }
    }
  }
}

/** The range as conditions on the variable, in the engine's terms. */
export function dateConditions(variable: string, value: string, today: Day): Condition[] {
  const { first, after } = dateBounds(value, today)
  const found: Condition[] = []
  if (first) found.push({ variable, operator: 'on_or_after', value: iso(first) })
  if (after) found.push({ variable, operator: 'before', value: iso(after) })
  return found
}

/** A custom range as a stored choice. */
export function rangeValue(from: string, to: string): string {
  return from || to ? `${DATE_PREFIX}${from}..${to}` : ''
}

/** The two days of a custom range, for the inputs that edit it. */
export function rangeParts(value: string): { from: string; to: string } {
  const choice = choiceOf(value)
  if (!value || DATE_PRESETS.some((preset) => preset.value === choice)) return { from: '', to: '' }
  const [from = '', to = ''] = choice.split('..')
  return { from, to }
}

export function isPreset(value: string): boolean {
  return DATE_PRESETS.some((preset) => preset.value === choiceOf(value))
}
