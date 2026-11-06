// Display helpers shared across pages.

/**
 * Text that is about to be put inside a string of HTML.
 *
 * Needed because two of the libraries here take HTML rather than text and give
 * no way to ask for text: an ECharts tooltip `formatter` returns a string that
 * is assigned as innerHTML, and a Leaflet tooltip does the same with a string
 * `bindTooltip`. React escapes everything it renders, so anywhere else in this
 * application a survey answer is already just characters - these two are the
 * exceptions, and a value label reading `<img src=x onerror=...>` runs in them.
 *
 * Labels come from uploaded data: a Stata value label, a Survey Solutions
 * export, a boundary file's feature properties, or whatever an interviewer
 * typed into a free-text field.
 */
export function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(
    /[&<>"']/g,
    (character) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!,
  )
}

/**
 * A number for display, showing decimals only where the value has them.
 *
 * `digits` is a maximum, not a fixed width: a count of 153 reads "153", never
 * "153.00", while a mean of 34.567 reads "34.57". Setting both the minimum and
 * the maximum - which this used to do - put two decimal places on every whole
 * number in every chart tooltip and table.
 *
 * Pass `fixed` for the case that genuinely wants a constant width, such as a
 * column of percentages read down the page.
 */
export function formatNumber(
  value: number | null | undefined,
  digits = 0,
  fixed = false,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  // Written out in full, with thousands separators. A count of interviews is
  // a number somebody reconciles against another system: "21.4k" cannot be
  // checked against 21,400, and rounds away the four hundred that the person
  // reading it is looking for.
  return value.toLocaleString(undefined, {
    minimumFractionDigits: fixed ? digits : 0,
    maximumFractionDigits: digits,
  })
}

export function formatValue(value: number | null | undefined, format = 'number', unit = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  switch (format) {
    case 'percent':
      return `${value.toFixed(1)}%`
    case 'currency':
      return `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}${unit ? ` ${unit}` : ''}`
    case 'decimal':
      return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    default:
      return `${formatNumber(value, Number.isInteger(value) ? 0 : 2)}${unit ? ` ${unit}` : ''}`
  }
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 3 })
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  const text = String(value)
  // ISO timestamps read better as plain dates in a table
  if (/^\d{4}-\d{2}-\d{2}T00:00:00/.test(text)) return text.slice(0, 10)
  return text
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

/** Seconds left, said the way somebody waiting would say it.
 *
 *  Precision nobody can act on reads as false precision: "143 seconds left"
 *  invites you to believe the number, and it is wrong by the time you have read
 *  it. Rounding to something coarse is the honest version.
 */
export function timeLeft(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return ''
  if (seconds < 10) return 'almost done'
  if (seconds < 90) return `about ${Math.round(seconds / 5) * 5} seconds left`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `about ${minutes} minute${minutes === 1 ? '' : 's'} left`
  const hours = Math.floor(minutes / 60)
  return `about ${hours}h ${(minutes % 60).toString().padStart(2, '0')}m left`
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return withTime ? date.toLocaleString() : date.toLocaleDateString()
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return 'never'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return 'never'
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} d ago`
  return new Date(value).toLocaleDateString()
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim()
}

/** What a map's pins stand for, in one line under the map.
 *
 * A pin has always been a place rather than an interview, and on a census map
 * it is a cell of ground holding several: "1,509 pins" alone would read as
 * 1,509 interviews to anybody who did not know that, and the number they came
 * for - how many located interviews there are - has to be the one on the page.
 */
export function mapSummary(
  pins: number,
  grouped?: { records: number; metres?: number | null } | null,
): string {
  if (!pins) return 'No located interviews'
  if (!grouped) return `${formatNumber(pins)} location(s)`
  const across =
    grouped.metres && grouped.metres >= 1000
      ? `${formatNumber(grouped.metres / 1000, 1)} km`
      : `${formatNumber(grouped.metres ?? 0)} m`
  return (
    `${formatNumber(grouped.records)} located interviews, drawn as ` +
    `${formatNumber(pins)} pins about ${across} across`
  )
}


/** What a pin standing for several places says about them, for its popup.
 *
 * A grouped pin takes the worst verdict among the places under it, because a
 * cell holding one disagreement is somewhere to go and look. That would read
 * as "every household here disagrees" with nothing to correct it, so the
 * popup says how many of them actually do.
 */
export function verdictMix(
  places: number,
  verdicts: Record<string, number> | undefined,
  labels: Record<string, string>,
): string {
  if (!verdicts || places <= 1) return ''
  const parts = Object.entries(verdicts)
    .filter(([, count]) => count > 0)
    .sort((left, right) => right[1] - left[1])
    .map(([status, count]) => `${formatNumber(count)} ${labels[status] ?? status}`)
  if (!parts.length) return ''
  return `${formatNumber(places)} locations here - ${parts.join(', ')}`
}
