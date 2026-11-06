import type { SnapshotSchedule } from '@/lib/types'

/** What a board that has never been scheduled starts from. */
export const DEFAULT_TIME = '08:00'

/**
 * A schedule with nothing missing, ready to put in a form.
 *
 * A board that has never been scheduled comes back with no times at all. A
 * form that renders `times[0] ?? '08:00'` then shows a time that is not in its
 * own state, and saving sends the empty list the state really held - so the
 * server refuses a schedule over a value the form was displaying, and the only
 * clue is a toast.
 *
 * Filling it once, here, keeps what is on screen and what is sent the same
 * thing.
 */
export function readySchedule(
  stored: SnapshotSchedule | null | undefined,
  blank: SnapshotSchedule,
): SnapshotSchedule {
  if (!stored) return blank
  return {
    ...stored,
    times: stored.times.length ? stored.times : blank.times,
    // Guard the same way: a keep of 0 would be a form offering to delete every
    // copy as soon as it took one.
    keep: stored.keep > 0 ? stored.keep : blank.keep,
  }
}
