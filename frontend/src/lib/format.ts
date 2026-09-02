// Display helpers shared across pages.

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
  const abs = Math.abs(value)
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (abs >= 10_000) return `${(value / 1_000).toFixed(1)}k`
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatValue(value: number | null | undefined, format = 'number', unit = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
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
  if (value === null || value === undefined || value === '') return '–'
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

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return '–'
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
