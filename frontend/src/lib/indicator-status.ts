/**
 * What an indicator's status badge says.
 *
 * On track, Watch and Critical are decided by the warning and critical
 * thresholds. An indicator with neither is "ok" by default - nothing was ever
 * asked of it - and a badge reading "On track" over it told the reader
 * something nobody had decided. It says what is missing instead.
 */
import type { BadgeTone } from '@/components/ui'
import type { IndicatorValue } from '@/lib/types'

export interface StatusBadge {
  tone: BadgeTone
  icon?: string
  label: string
  /** Why it says this, where that is not obvious. */
  title?: string
}

// On track carries no glyph: the state nobody has to act on should not be
// decorated, and the three that do keep theirs.
export const INDICATOR_STATE: Record<string, StatusBadge> = {
  ok: { tone: 'success', label: 'On track' },
  warning: { tone: 'warning', icon: '▲', label: 'Watch' },
  critical: { tone: 'danger', icon: '■', label: 'Critical' },
  unknown: { tone: 'neutral', icon: '-', label: 'No data' },
}

export function indicatorBadge(
  value: Pick<IndicatorValue, 'status' | 'target_value'> & { judged?: boolean },
): StatusBadge {
  if (value.status === 'ok' && value.judged === false) {
    return value.target_value == null
      ? {
          tone: 'neutral',
          label: 'No target',
          title: 'Give it a target and warning and critical thresholds to have it marked On track, Watch or Critical.',
        }
      : {
          tone: 'neutral',
          label: 'No thresholds',
          title: 'Set warning and critical thresholds to have it marked On track, Watch or Critical.',
        }
  }
  return INDICATOR_STATE[value.status] ?? INDICATOR_STATE.unknown
}
