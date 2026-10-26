/**
 * How an indicator has moved, said in a line or two under its number.
 *
 * The server works the figures out from the indicator's stored history - see
 * `movement` in app/services/monitoring.py - and leaves out whatever that
 * history cannot support. This only words them: "+212 since yesterday", "at
 * 190 a day, reaches 15,040 on 18 Nov", "needs 240 a day to make 30 Nov". The
 * wording lives here, apart from the tiles, so the Indicators page, the
 * dashboard tile and the Overview say it the same way.
 */
import { formatNumber } from '@/lib/format'

export interface Movement {
  change_day?: number | null
  change_week?: number | null
  pace_per_day?: number | null
  /** How many days the pace was averaged over. */
  pace_days?: number
  projected_at?: string
  /** Moving towards the target, but more than ten years from it. */
  projected_beyond?: boolean
  /** Whether the projection lands on or before the target date. */
  on_course?: boolean
  target_date?: string | null
  days_left?: number
  needed_per_day?: number
  reached?: boolean
}

export interface MovementLine {
  text: string
  /** Good or bad news by the indicator's own direction; plain where neither. */
  tone: 'good' | 'bad' | 'plain'
}

interface Shape {
  format: string
  unit: string
  direction: string
  target: number | null
}

/** A change, signed, in the indicator's own terms. A percentage moves in
 *  points: a rate going from 40% to 42% went up two points, not 2%. */
export function signed(change: number, format: string, unit: string): string {
  const sign = change > 0 ? '+' : change < 0 ? '-' : ''
  return `${sign}${amount(Math.abs(change), format, unit)}`
}

function amount(value: number, format: string, unit: string): string {
  // Whole numbers for anything counted in tens; a decimal where the figure
  // is small enough that rounding would hide it.
  const digits = value !== 0 && Math.abs(value) < 10 ? 1 : 0
  const number = formatNumber(value, digits)
  if (format === 'percent') return `${number} pts`
  return unit ? `${number} ${unit}` : number
}

function day(iso: string): string {
  // A target date is a calendar day, so read as one, not shifted by a zone.
  const [year, month, date] = iso.slice(0, 10).split('-').map(Number)
  return new Date(year, month - 1, date).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })
}

function tone(change: number, direction: string): MovementLine['tone'] {
  if (change === 0 || direction === 'neutral') return 'plain'
  const up = change > 0
  return (direction === 'lower_is_better' ? !up : up) ? 'good' : 'bad'
}

/** The lines to put under an indicator's number, most useful first. */
export function movementLines(movement: Movement | undefined, shape: Shape): MovementLine[] {
  if (!movement) return []
  const lines: MovementLine[] = []
  const { format, unit, direction, target } = shape

  const changes: string[] = []
  if (typeof movement.change_day === 'number') {
    changes.push(
      movement.change_day === 0
        ? 'no change since yesterday'
        : `${signed(movement.change_day, format, unit)} since yesterday`,
    )
  }
  if (typeof movement.change_week === 'number') {
    changes.push(`${signed(movement.change_week, format, unit)} in a week`)
  }
  if (changes.length) {
    const headline = movement.change_day ?? movement.change_week ?? 0
    lines.push({ text: capitalised(changes.join(' · ')), tone: tone(headline, direction) })
  }

  if (movement.reached || target === null) {
    // Past the target there is nowhere to project to, and the variance line
    // already says by how much. Without one, only the pace means anything.
    if (target === null && typeof movement.pace_per_day === 'number' && movement.pace_per_day !== 0) {
      lines.push({ text: `Averaging ${signed(movement.pace_per_day, format, unit)} a day`, tone: 'plain' })
    }
    return lines
  }

  const pace = movement.pace_per_day
  const goal = format === 'percent' ? `${formatNumber(target, 1)}%` : amount(target, format, unit)
  if (movement.projected_at && typeof pace === 'number') {
    let text = `At ${amount(Math.abs(pace), format, unit)} a day, reaches ${goal} on ${day(movement.projected_at)}`
    let projectionTone: MovementLine['tone'] = 'plain'
    if (movement.target_date && typeof movement.on_course === 'boolean') {
      text += movement.on_course ? ', in time' : `, after ${day(movement.target_date)}`
      projectionTone = movement.on_course ? 'good' : 'bad'
    }
    lines.push({ text, tone: projectionTone })
  } else if (movement.projected_beyond && typeof pace === 'number') {
    lines.push({
      text: `At ${amount(Math.abs(pace), format, unit)} a day, ${goal} is more than ten years away`,
      tone: 'bad',
    })
  } else if (typeof pace === 'number' && direction !== 'neutral') {
    lines.push({ text: 'Not moving towards the target this week', tone: 'bad' })
  }

  if (movement.target_date && typeof movement.days_left === 'number') {
    if (movement.days_left <= 0) {
      lines.push({ text: `The target date, ${day(movement.target_date)}, has passed`, tone: 'bad' })
    } else if (typeof movement.needed_per_day === 'number' && !movement.on_course) {
      // Said only where the current pace will not do it. On course, the line
      // above already says so, and a second figure is one more to read.
      lines.push({
        text: `Needs ${amount(movement.needed_per_day, format, unit)} a day to make ${day(movement.target_date)}`,
        tone: 'plain',
      })
    }
  }
  return lines
}

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
