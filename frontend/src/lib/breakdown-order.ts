/**
 * How a broken-down indicator's groups are presented: in what order, and as
 * what.
 *
 * A breakdown arrives in whatever order the query answered in, which is no
 * order at all once there are sixty enumeration areas on the chart: a reader
 * looking for the areas that are behind has to read every bar to find them,
 * and a reader looking up one area has to read every bar to find that.
 *
 * Which order is right depends on the question, so it is a choice on the
 * widget rather than a decision taken here. The default answers the question
 * a monitoring board exists for - who is behind - and falls back to the
 * largest first where there are no quotas to be behind.
 */
import { by } from '@/lib/collections'

export type BreakdownOrder = 'behind' | 'done' | 'largest' | 'name'

export const BREAKDOWN_ORDERS: { id: BreakdownOrder; label: string }[] = [
  { id: 'behind', label: 'Furthest behind first' },
  { id: 'done', label: 'Most complete first' },
  { id: 'largest', label: 'Largest first' },
  { id: 'name', label: 'By name' },
]

export interface Progress {
  value: number
  target: number | null
  percent: number | null
  status?: string
}

/**
 * The groups, in the order asked for.
 *
 * `progress` is the per-group report: its value, its own quota and how far
 * through it is. Where a group has no quota there is nothing to be behind,
 * so those sort after the ones that have one rather than counting as zero
 * per cent and crowding the top of a chart that is asking who needs help.
 */
export function orderBreakdown(
  groups: [string, number][],
  progress: Record<string, Progress | undefined>,
  order: BreakdownOrder = 'behind',
): [string, number][] {
  const rows = [...groups]
  const share = (key: string) => progress[key]?.percent ?? null
  const quoted = rows.some(([key]) => (progress[key]?.target ?? null) !== null)

  if (order === 'name') {
    return rows.sort(by(([key]) => key))
  }
  if (order === 'largest' || !quoted) {
    // Nothing has a quota, so "behind" and "complete" have no meaning: the
    // honest fallback is the one order that always does.
    return rows.sort((one, other) => other[1] - one[1])
  }
  return rows.sort((one, other) => {
    const mine = share(one[0])
    const theirs = share(other[0])
    // A group with no quota of its own goes last either way: it is not behind
    // and it is not finished, it is simply not being judged.
    if (mine === null && theirs === null) return other[1] - one[1]
    if (mine === null) return 1
    if (theirs === null) return -1
    return order === 'done' ? theirs - mine : mine - theirs
  })
}

export type BreakdownView = 'chart' | 'table'

export interface BreakdownRow {
  group: string
  value: number
  target: number | null
  percent: number | null
  /** target - value, where there is a target and the work is not done. */
  shortfall: number | null
  status: string
}

/**
 * The groups as rows, for reading rather than for looking at.
 *
 * Sixty bars in a tile the size of a postcard is a smear; the same sixty as
 * lines of figures is a list somebody can read down, quote from and check.
 * Both are drawn from exactly the same numbers, so a reader comparing the two
 * forms of one widget finds no difference between them.
 */
export function breakdownRows(
  groups: [string, number][],
  progress: Record<string, Progress | undefined>,
): BreakdownRow[] {
  return groups.map(([group, value]) => {
    const found = progress[group]
    const target = found?.target ?? null
    return {
      group,
      value,
      target,
      percent: found?.percent ?? null,
      shortfall: target === null ? null : Math.max(target - value, 0),
      status: found?.status ?? 'unknown',
    }
  })
}
