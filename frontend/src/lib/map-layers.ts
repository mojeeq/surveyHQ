/**
 * What a map's layers are and how its key lists them, apart from the map.
 *
 * The drawing is Leaflet's, in components/MapWidget; what each layer is
 * called, which colour it is, how many it counts and in what order the key
 * lists them is decided here, where it can be tested without a browser.
 */
import { escapeHtml, formatNumber } from '@/lib/format'

/** A pin's colour when nothing about it is being judged. */
export const DEFAULT_POINT_FILL = '#3b82f6'

export interface MapPoint {
  lat: number
  lon: number
  /** The aggregated value: how many interviews, or the sum asked for. */
  value: number
  /** How many rows are behind the pin, which is not the value when it is a sum. */
  rows: number
  /** Set when the map is checking a recorded area against where the point is. */
  area_status?: AreaStatus
  area_expected?: string | null
  recorded_area_label?: unknown
  /** How many locations a grouped pin stands for, and how they each came out.
      Absent on a map drawn one pin per location. */
  places?: number
  area_verdicts?: Record<string, number>
  /** How many other records lie within the duplicate distance of this one. */
  duplicates?: number
  /** On a grouped pin: how many of its locations have such a neighbour. */
  duplicate_places?: number
  /** On a second-location pin: how far each GPS reading beside it is, in metres. */
  gps?: number[]
  [detail: string]: unknown
}

/** The location entered by hand, beside the GPS: its pins and their verdicts. */
export interface ManualLayer {
  points: MapPoint[]
  counts?: Partial<Record<AreaStatus, number>> | null
  records: number
  truncated?: boolean
}

/** One record whose GPS and hand-entered locations are far apart. */
export interface DiscrepancyLine {
  gps: [number, number]
  manual: [number, number]
  metres: number
  rows: number
  recorded_area_label?: unknown
}

export interface LineLayer {
  metres: number
  lines: DiscrepancyLine[]
  total: number
  truncated?: boolean
}

export type AreaStatus = 'match' | 'mismatch' | 'outside' | 'unrecorded'

/**
 * How each verdict is drawn, in the order the legend lists them.
 *
 * The mismatch is red and the largest because it is the finding: a record
 * whose enumeration area disagrees with the ground under it is a code typed
 * wrong, an interviewer in the wrong area, or a boundary the field reads
 * differently from the office. Agreement is the quiet majority and is drawn
 * as such, so a screen of green with four red dots reads correctly at a
 * glance rather than needing to be counted.
 */
export const VERDICTS: Record<AreaStatus, { label: string; color: string; radius: number }> = {
  mismatch: { label: 'Area does not match the GPS', color: '#d7301f', radius: 7 },
  outside: { label: 'Outside every area in the layer', color: '#f0a202', radius: 6 },
  unrecorded: { label: 'No area recorded', color: '#6a51a3', radius: 6 },
  match: { label: 'Area agrees with the GPS', color: '#2c9e4b', radius: 4 },
}

export const VERDICT_ORDER: AreaStatus[] = ['mismatch', 'outside', 'unrecorded', 'match']

/**
 * The hand-entered location's verdicts: the same four, in colours of their
 * own, so a reader can tell a disagreeing GPS pin from a disagreeing manual
 * one with both layers ticked. Blue and yellow are the two a field office's
 * own maps have used for these.
 */
export const MANUAL_COLORS: Record<AreaStatus, string> = {
  match: '#3b5bdb',
  mismatch: '#ffd43b',
  outside: '#94a3b8',
  unrecorded: '#c084fc',
}

export function manualVerdictLabel(status: AreaStatus, name: string): string {
  return {
    match: `${name} location agrees with the area`,
    mismatch: `${name} location is in another area`,
    outside: `${name} location outside every area`,
    unrecorded: `${name} location, no area recorded`,
  }[status]
}

/** A ring round each duplicated reading, on top of whatever colour it is. */
export const DUPLICATE_COLOR = '#111827'
/** Areas the fieldwork has reached. */
export const COVERAGE_COLOR = '#f59e0b'

/** A distance as a reader says it. */
export function formatMetres(metres: number): string {
  return metres < 1000
    ? `${Math.round(metres)} m`
    : `${(metres / 1000).toFixed(metres < 10_000 ? 1 : 0)} km`
}

/** One layer a reader can tick on and off, as the map's key lists it. */
export interface MapCategory {
  key: string
  text: string
  color: string
  kind: 'dot' | 'ring' | 'line' | 'area'
  count: number
  /** Out of how many, where that is the point: 12 of 30 areas reached. */
  of?: number
}

/** A colour safe to write into a style attribute, or the default. */
function safeColour(colour: string): string {
  return /^#[0-9a-f]{3,8}$/i.test(colour) || /^rgba?\([\d\s.,%/]+\)$/i.test(colour)
    ? colour
    : DEFAULT_POINT_FILL
}

/**
 * A layer's line in the tick-box list: a swatch, its name and how many.
 *
 * Leaflet writes this as markup, so the name - which can carry a variable's
 * name or a label from the data - is escaped and the colour is checked.
 */
export function categoryLabel(category: MapCategory): string {
  const colour = safeColour(category.color)
  const swatch =
    category.kind === 'line'
      ? '<i class="map-key-line"></i>'
      : category.kind === 'ring'
        ? `<i class="map-key-ring" style="border-color:${colour}"></i>`
        : category.kind === 'area'
          ? `<i class="map-key-area" style="background:${colour}"></i>`
          : `<i class="map-key-dot" style="background:${colour}"></i>`
  return (
    `<span class="map-key">${swatch}<span>${escapeHtml(category.text)}</span>` +
    `<span class="map-key-count">${escapeHtml(
      formatNumber(category.count) + (category.of !== undefined ? ` of ${formatNumber(category.of)}` : ''),
    )}</span></span>`
  )
}

/**
 * Every layer the map has, in the order the key lists them: the GPS pins by
 * verdict, the duplicates, the hand-entered pins by verdict, the lines.
 * What is not on this map is not listed.
 */
export function mapCategories({
  points,
  areaCounts,
  duplicates,
  manual,
  lines,
  manualName = 'Manual',
  pointColor,
}: {
  points: MapPoint[]
  areaCounts?: Partial<Record<AreaStatus, number>>
  duplicates?: { metres: number; places: number } | null
  manual?: ManualLayer | null
  lines?: LineLayer | null
  manualName?: string
  pointColor?: string
}): MapCategory[] {
  const found: MapCategory[] = []
  const records = (list: MapPoint[]) => list.reduce((sum, point) => sum + (Number(point.rows) || 0), 0)
  if (points.some((point) => point.area_status)) {
    for (const status of VERDICT_ORDER) {
      const count = areaCounts?.[status] ?? points.filter((point) => point.area_status === status).length
      if (!count) continue
      found.push({ key: `gps:${status}`, text: VERDICTS[status].label, color: VERDICTS[status].color, kind: 'dot', count })
    }
  } else if (points.length) {
    found.push({
      key: 'gps:all',
      text: manual ? 'GPS locations' : 'Interview locations',
      color: pointColor || DEFAULT_POINT_FILL,
      kind: 'dot',
      count: records(points),
    })
  }
  if (duplicates) {
    found.push({
      key: 'duplicates',
      text: `Duplicated GPS (within ${formatMetres(duplicates.metres)})`,
      color: DUPLICATE_COLOR,
      kind: 'ring',
      count: duplicates.places,
    })
  }
  if (manual) {
    if (manual.points.some((point) => point.area_status)) {
      for (const status of VERDICT_ORDER) {
        const count =
          manual.counts?.[status] ?? manual.points.filter((point) => point.area_status === status).length
        if (!count) continue
        found.push({
          key: `manual:${status}`,
          text: manualVerdictLabel(status, manualName),
          color: MANUAL_COLORS[status],
          kind: 'dot',
          count,
        })
      }
    } else if (manual.points.length) {
      found.push({
        key: 'manual:all',
        text: `${manualName} locations`,
        color: MANUAL_COLORS.match,
        kind: 'dot',
        count: manual.records,
      })
    }
  }
  if (lines) {
    found.push({
      key: 'lines',
      text: `GPS and ${manualName.toLowerCase()} over ${formatMetres(lines.metres)} apart`,
      color: '#ffffff',
      kind: 'line',
      count: lines.total,
    })
  }
  return found
}

/** The same four, said in the words a count reads with: "3 disagree". */
export const VERDICT_LABELS: Record<AreaStatus, string> = {
  mismatch: 'disagree with the GPS',
  outside: 'outside every area',
  unrecorded: 'with no area recorded',
  match: 'agree',
}

